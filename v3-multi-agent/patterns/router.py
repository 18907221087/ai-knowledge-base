"""
Router 模式 — 基于意图分类的请求路由

Router 是最常见的 Agent 设计模式之一，核心思想是"先分类，再分发"：
1. 接收用户查询
2. 分类意图（关键词 + LLM 兜底）
3. 路由到对应的处理器

适用场景: 多功能 Agent 需要将不同类型请求分发到专门处理器。
比如一个 Agent 既要能查 GitHub、又能查本地知识库、还能闲聊，
用 Router 模式可以避免一个巨型 prompt 处理所有情况，降低成本和延迟。

设计要点:
- 每个处理器只负责一种意图，职责单一，易于扩展
- 关键词匹配作为快速路径，零 LLM 调用成本
- LLM 分类作为兜底，处理模糊意图，确保鲁棒性
"""

import glob as glob_mod
import json
import os
import urllib.request
from typing import Callable

# 导入统一的 LLM 调用工具
# - chat(): 普通对话，返回自然语言文本
# - chat_json(): 返回 JSON 结构化数据（本文件未直接使用，但可供扩展）
from workflows.model_client import chat, chat_json


# =============================================================================
# 处理器定义 — 每个处理器负责一种意图
#
# 所有处理器遵循统一的函数签名: (query: str) -> str
# 这样路由器就可以用字典统一调度，无需 if-else 分支
# =============================================================================

def github_search_handler(query: str) -> str:
    """GitHub 搜索处理器：搜索相关仓库并返回摘要

    工作流程:
    1. 读取 GITHUB_TOKEN 环境变量（可选，提高 API 速率限制）
    2. 清理查询词，去掉用户自然语言中的非搜索词
    3. 调用 GitHub Search API，按星数排序，取前 5 条
    4. 格式化结果并返回

    Args:
        query: 用户原始查询文本，如 "搜索最新的 MCP 实现"

    Returns:
        格式化后的仓库列表字符串，或错误信息
    """
    # 读取 GitHub Token（可选），有 Token 的话请求限制从 60次/小时 提升到 5000次/小时
    token = os.getenv("GITHUB_TOKEN", "")

    # 构造 HTTP 请求头，指定接受 v3 版本的 GitHub JSON API
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    # 清理查询词：去掉用户附加的自然语言指令词（如"搜索"、"github"）
    # 只保留核心搜索关键词，避免干扰 Search API 的查询语义
    search_query = query.replace("搜索", "").replace("github", "").strip()

    # 构造 GitHub Search API URL
    # ?q=       搜索关键词
    # &sort=stars  按星数降序排列
    # &per_page=5  每次只取前 5 条结果，控制输出长度
    url = f"https://api.github.com/search/repositories?q={search_query}&sort=stars&per_page=5"

    try:
        # 发起 HTTP GET 请求（使用 urllib 标准库，零依赖）
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            # 解码响应体并解析 JSON
            data = json.loads(resp.read().decode())

        # 逐条格式化输出结果
        results = []
        for repo in data.get("items", []):
            # 格式: - [用户名/仓库名](链接) ⭐星数 — 项目描述
            results.append(
                f"- [{repo['full_name']}]({repo['html_url']}) "
                f"⭐{repo['stargazers_count']} — "
                f"{repo.get('description', '无描述')}"
            )

        # 有结果时逐行展示，无结果时给出提示
        return (
            f"GitHub 搜索结果:\n" + "\n".join(results)
            if results
            else "未找到相关仓库"
        )

    except Exception as e:
        # 网络错误、API 限流、Token 无效等情况统一捕获
        return f"GitHub 搜索失败: {e}"


def _load_articles(articles_dir: str) -> list[dict]:
    """从目录中扫描所有 JSON 文章文件，构建内存索引

    knowledge/articles/ 下每篇文章是一个独立的 JSON 文件，
    文件名格式为 {来源}-{日期}-{序号}.json（如 rss-20260518-001.json）。
    此函数遍历目录下所有 .json 文件，读取每篇的关键字段，
    返回一个文章列表供后续检索使用。

    Args:
        articles_dir: articles 目录的绝对路径

    Returns:
        文章字典列表，每项包含 id, title, summary, tags, score, source 等字段
    """
    articles = []
    # 扫描目录下所有 .json 文件
    json_files = glob_mod.glob(os.path.join(articles_dir, "*.json"))
    for filepath in json_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                article = json.load(f)
            # 只保留检索和展示需要的字段，减少内存占用
            articles.append({
                "id": article.get("id", ""),
                "title": article.get("title", ""),
                "summary": article.get("summary", ""),
                "tags": article.get("tags", []),
                "score": article.get("score", 0),
                "source": article.get("source", ""),
                "source_url": article.get("source_url", ""),
            })
        except (json.JSONDecodeError, OSError):
            # 跳过损坏或无法解析的文件
            continue
    return articles


def knowledge_query_handler(query: str) -> str:
    """知识库查询处理器：从本地知识库检索相关条目

    数据来源: knowledge/articles/ 目录下的所有 .json 文件
    （每篇文章一个独立文件，非单一 index.json）

    检索采用两阶段策略:
    第一阶段 — 关键词精确匹配（快，零 Token 成本）
      匹配范围: title、tags、summary 三个字段
      不足: 无法理解同义表达（如"训练"匹配不到"fine-tuning"标签）
    第二阶段 — LLM 语义检索（慢，但能理解模糊语义）
      将候选文章列表发给 LLM，由模型判断语义相关性

    Args:
        query: 用户查询文本

    Returns:
        检索结果字符串，或空库提示
    """
    # 计算 knowledge/articles/ 目录的绝对路径
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    articles_dir = os.path.join(base_dir, "knowledge", "articles")

    # 目录不存在 → 知识库未初始化
    if not os.path.exists(articles_dir):
        return "知识库为空，请先运行采集工作流。"

    # 扫描所有 JSON 文件，构建内存索引
    articles = _load_articles(articles_dir)

    # 目录存在但无有效 JSON → 同样算空库
    if not articles:
        return "知识库为空，请先运行采集工作流。"

    # ---- 第一阶段: 关键词精确匹配 ----
    # 在 title、tags、summary 三个字段中做子串匹配
    # 匹配到任一字段即认为相关，匹配多个字段说明相关性更高
    query_lower = query.lower()
    matches = []
    for article in articles:
        # 计算命中次数（多字段命中 = 更高相关度）
        hits = 0
        if query_lower in article["title"].lower():
            hits += 3  # 标题命中权重最高
        if any(query_lower in tag.lower() for tag in article["tags"]):
            hits += 2  # 标签命中权重中等
        if query_lower in article["summary"].lower():
            hits += 1  # 摘要命中权重较低

        if hits > 0:
            matches.append((article, hits))

    if matches:
        # 按命中次数降序排列，相关度高的排前面
        matches.sort(key=lambda x: x[1], reverse=True)
        lines = []
        for article, _ in matches[:10]:
            # 每行展示: 标题 [标签1, 标签2] (评分: X) — 摘要前60字
            preview = article["summary"][:60] + "..." if article["summary"] else "暂无摘要"
            tags_str = ", ".join(article["tags"][:5]) if article["tags"] else "未分类"
            lines.append(f"- {article['title']} [{tags_str}] (评分: {article['score']}) — {preview}")
        return f"找到 {len(matches)} 条相关知识:\n" + "\n".join(lines)

    # ---- 第二阶段: LLM 语义检索 ----
    # 精确匹配无结果时，用 LLM 理解查询意图，从所有文章中找语义相关条目
    # 只发送前 20 篇文章的标题和摘要给 LLM，控制 context 大小
    preview_data = []
    for a in articles[:20]:
        preview_data.append({
            "id": a["id"],
            "title": a["title"],
            "summary": a.get("summary", ""),
            "tags": a.get("tags", []),
        })

    prompt = f"""用户查询: {query}

知识库中可用文章:
{json.dumps(preview_data, ensure_ascii=False, indent=2)}

请从上面的文章中找出与查询最相关的条目（最多5条），列出它们的 id 和标题，并解释相关性。"""

    # 调用 LLM，system 角色设定为检索助手
    # chat() 返回 (响应文本, token用量)，这里只关心文本
    result, _ = chat(prompt, system="你是知识库检索助手。")
    return result


def general_chat_handler(query: str) -> str:
    """通用对话处理器：使用 LLM 直接回答技术问题

    这是最"万能"的处理器，负责兜底 Google 搜索和知识库都覆盖不了的场景，
    比如纯技术咨询、概念解释、代码建议等。

    使用 system prompt 约束回答风格: 专业、简洁、准确

    Args:
        query: 用户查询文本

    Returns:
        LLM 生成的回答文本
    """
    result, _ = chat(
        query,
        system="你是一个专业的 AI 技术顾问。简洁、准确地回答技术问题。",
    )
    return result


# =============================================================================
# 路由器核心 — 意图分类 + 处理器调度
#
# 核心数据结构:
# - HANDLERS:    意图 → 处理器的映射表（注册表模式）
# - KEYWORD_RULES: 关键词列表 → 意图的快速匹配表
#
# 工作流程:
# query → classify_intent() → HANDLERS[intent](query) → response
# =============================================================================

# 处理器注册表 — 所有处理器在这里统一注册
# 键: 意图名称（字符串标识）
# 值: 处理器函数（可调用对象，签名 (str) -> str）
# 新增处理器只需在这里加一行，无需修改路由逻辑
HANDLERS: dict[str, Callable[[str], str]] = {
    "github_search": github_search_handler,
    "knowledge_query": knowledge_query_handler,
    "general_chat": general_chat_handler,
}

# 关键词路由规则 — 快速路径，不消耗 LLM Token
# 每条规则是一个二元组: (关键词列表, 意图名称)
# 只要用户查询包含列表中任意一个关键词，就匹配到对应意图
# 规则按顺序匹配：先匹配到的优先，因此建议高频规则放前面
KEYWORD_RULES: list[tuple[list[str], str]] = [
    (["github", "仓库", "repo", "搜索项目", "trending"], "github_search"),
    (["知识库", "查询", "检索", "已收录", "knowledge"], "knowledge_query"),
]


def classify_intent(query: str) -> str:
    """意图分类：关键词匹配优先，LLM 兜底

    两层分类策略:
    1. 关键词快速匹配 — 毫秒级，零 Token 成本，覆盖 80% 常见场景
    2. LLM 语义分类   — 秒级，消耗 Token，处理模糊/新出现的表达

    这种"快慢结合"的设计平衡了成本和准确性：
    - 高频场景走快速通道，省钱又快
    - 低频/模糊场景走 LLM，保证不误判

    Args:
        query: 用户原始查询文本

    Returns:
        意图名称字符串，保证在 HANDLERS 字典中存在
        （兜底为 "general_chat"）
    """
    # 统一转小写，避免大小写导致关键词匹配失败
    query_lower = query.lower()

    # ---- 第一层: 关键词快速匹配 ----
    # 遍历所有规则，只要查询文本包含规则中任一关键词即可命中
    # 例如用户说"帮我查一下 AI Agent" → 匹配到 knowledge_query
    for keywords, intent in KEYWORD_RULES:
        # any() 短路求值：匹配到第一个关键词就停止
        if any(kw in query_lower for kw in keywords):
            return intent

    # ---- 第二层: LLM 语义分类 ----
    # 关键词未命中时，用 LLM 理解用户意图
    # 构造分类 prompt：告诉 LLM 有哪些可选类别及其含义
    prompt = f"""请判断以下用户查询的意图类别。

查询: {query}

可选类别:
- github_search: 用户想搜索 GitHub 上的项目或仓库
- knowledge_query: 用户想查询已有的知识库内容
- general_chat: 一般性的技术问题或闲聊

请只返回类别名称（如 github_search），不要返回其他内容。"""

    # max_tokens=50 限制输出长度，因为只需要一个意图名
    result, _ = chat(prompt, system="你是意图分类器。只返回类别名称。", max_tokens=50)
    intent = result.strip().lower()

    # 安全校验: 确保 LLM 返回的意图名在注册表中存在
    # 防止 LLM 返回了未定义的意图导致 KeyError
    if intent in HANDLERS:
        return intent
    # 兜底: 无法识别的意图统一按通用对话处理
    return "general_chat"


def route(query: str) -> str:
    """路由器入口：分类意图并调用对应处理器

    这是整个 Router 模式的主入口，调用方只需传 query，无需关心内部逻辑。
    三步走: 分类 → 查找处理器 → 执行

    Args:
        query: 用户查询文本

    Returns:
        处理器的响应文本
    """
    # Step 1: 分类意图（关键词 or LLM）
    intent = classify_intent(query)

    # Step 2: 从注册表中查找对应处理器函数
    # HANDLERS 保证了 intent 一定存在（classify_intent 已兜底）
    handler = HANDLERS[intent]

    # Step 3: 打印意图信息（方便调试），调用处理器并返回结果
    print(f"[Router] 意图: {intent}")
    return handler(query)


# --- 命令行测试入口 ---
if __name__ == "__main__":
    import sys

    # 从命令行参数拼接查询文本，无参数时使用默认测试查询
    # 用法示例: python patterns/router.py 搜索 MCP 相关的项目
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "知识库搜索最近的 AI Agent 框架"

    print(f"查询: {query}\n")
    print(route(query))
