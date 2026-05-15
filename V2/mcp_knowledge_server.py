#!/usr/bin/env python3
"""
MCP Knowledge Server — 基于 JSON-RPC 2.0 over stdio 的本地知识库搜索服务。

让 AI 工具（如 Claude Desktop、continue.dev）可以通过 MCP 协议
搜索 knowledge/articles/ 目录下的技术文章。

启动方式：
    python mcp_knowledge_server.py

MCP 协议参考：https://spec.modelcontextprotocol.io/
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
import sys,io
# 强制设置 stdout/stderr 编码为 UTF-8，确保 Windows 终端正常输出 Unicode 字符
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)
# ── JSON-RPC 2.0 错误码 ────────────────────────────────────────────────────

JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603

# MCP 协议自定义错误码
MCP_TOOL_NOT_FOUND = -32000


def jsonrpc_error(code: int, message: str, req_id: Any = None) -> dict[str, Any]:
    """构造 JSON-RPC 2.0 错误响应"""
    return {
        "jsonrpc": "2.0",
        "error": {"code": code, "message": message},
        "id": req_id,
    }


def jsonrpc_response(result: Any, req_id: Any) -> dict[str, Any]:
    """构造 JSON-RPC 2.0 成功响应"""
    return {
        "jsonrpc": "2.0",
        "result": result,
        "id": req_id,
    }


# ── 知识库管理 ─────────────────────────────────────────────────────────────

class KnowledgeBase:
    """管理知识库文章的加载、搜索与统计"""

    def __init__(self, articles_dir: str):
        self.articles_dir = Path(articles_dir)
        self.articles: list[dict[str, Any]] = []

    def load(self) -> int:
        """加载 articles_dir 下所有 JSON 文件，返回加载数量"""
        self.articles.clear()
        if not self.articles_dir.exists():
            log(f"[WARN] 知识库目录不存在: {self.articles_dir}")
            return 0

        for filepath in sorted(self.articles_dir.glob("*.json")):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "id" in data:
                    self.articles.append(data)
                else:
                    log(f"[WARN] 跳过非文章格式文件: {filepath.name}")
            except (json.JSONDecodeError, OSError) as e:
                log(f"[WARN] 读取失败 {filepath.name}: {e}")
                continue

        log(f"[INFO] 已加载 {len(self.articles)} 篇文章")
        return len(self.articles)

    def search(self, keyword: str, limit: int = 5) -> list[dict[str, Any]]:
        """按关键词搜索文章标题和摘要，返回匹配列表"""
        if not keyword.strip():
            return []

        keyword_lower = keyword.lower()
        results: list[dict[str, Any]] = []

        for article in self.articles:
            title = str(article.get("title", "")).lower()
            summary = str(article.get("summary", "")).lower()
            tags = [t.lower() for t in article.get("tags", [])]

            # 在标题、摘要、标签中匹配关键词
            if (keyword_lower in title
                    or keyword_lower in summary
                    or any(keyword_lower in tag for tag in tags)):
                results.append(self._format_article_preview(article))

            if len(results) >= limit:
                break

        return results[:limit]

    def get_by_id(self, article_id: str) -> dict[str, Any] | None:
        """按 ID 获取文章完整内容"""
        for article in self.articles:
            if article.get("id") == article_id:
                return article
        return None

    def stats(self) -> dict[str, Any]:
        """返回知识库统计信息"""
        total = len(self.articles)

        # 统计来源分布
        sources: dict[str, int] = {}
        for article in self.articles:
            source = article.get("source", "unknown")
            # RSS 来源格式为 "rss:SourceName"，合并为 "rss"
            if source.startswith("rss:"):
                source = "rss"
            sources[source] = sources.get(source, 0) + 1

        # 统计热门标签（TOP 20）
        tag_counter: dict[str, int] = {}
        for article in self.articles:
            for tag in article.get("tags", []):
                tag_counter[tag] = tag_counter.get(tag, 0) + 1
        hot_tags = sorted(tag_counter.items(), key=lambda x: x[1], reverse=True)[:20]

        # 统计平均分
        scores = [a["score"] for a in self.articles if "score" in a]
        avg_score = round(sum(scores) / len(scores), 2) if scores else 0

        # 统计受众分布
        audiences: dict[str, int] = {}
        for article in self.articles:
            audience = article.get("audience", "unknown")
            audiences[audience] = audiences.get(audience, 0) + 1

        return {
            "total_articles": total,
            "source_distribution": sources,
            "hot_tags": [{"tag": tag, "count": count} for tag, count in hot_tags],
            "avg_score": avg_score,
            "audience_distribution": audiences,
        }

    @staticmethod
    def _format_article_preview(article: dict[str, Any]) -> dict[str, Any]:
        """格式化文章预览（搜索结果显示用）"""
        return {
            "id": article.get("id", ""),
            "title": article.get("title", ""),
            "source": article.get("source", ""),
            "summary": article.get("summary", ""),
            "score": article.get("score"),
            "tags": article.get("tags", []),
            "published_at": article.get("published_at", ""),
        }


# ── MCP 请求处理 ───────────────────────────────────────────────────────────

class MCPServer:
    """MCP JSON-RPC 2.0 服务端"""

    SERVER_NAME = "knowledge-base-server"
    SERVER_VERSION = "1.0.0"

    def __init__(self, kb: KnowledgeBase):
        self.kb = kb
        self.initialized = False

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """
        处理单个 JSON-RPC 请求，返回响应字典。
        如果是通知（无 id），返回 None。
        """
        req_id = request.get("id")

        # 校验 JSON-RPC 基本格式
        if request.get("jsonrpc") != "2.0":
            return jsonrpc_error(JSONRPC_INVALID_REQUEST,
                                 "缺少或无效的 jsonrpc 字段", req_id)

        method = request.get("method", "")
        params = request.get("params", {})

        # 路由分发
        try:
            if method == "initialize":
                return self._handle_initialize(params, req_id)
            elif method == "notifications/initialized":
                return None  # 无需响应
            elif method == "tools/list":
                return self._handle_tools_list(req_id)
            elif method == "tools/call":
                return self._handle_tools_call(params, req_id)
            else:
                return jsonrpc_error(JSONRPC_METHOD_NOT_FOUND,
                                     f"未知方法: {method}", req_id)
        except Exception as e:
            log(f"[ERROR] 处理请求失败: {e}")
            return jsonrpc_error(JSONRPC_INTERNAL_ERROR,
                                 f"内部错误: {str(e)}", req_id)

    # ── MCP 方法实现 ───────────────────────────────────────────────────

    def _handle_initialize(self, params: dict[str, Any],
                           req_id: Any) -> dict[str, Any]:
        """处理 initialize 请求"""
        self.initialized = True
        return jsonrpc_response({
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": self.SERVER_NAME,
                "version": self.SERVER_VERSION,
            },
            "capabilities": {
                "tools": {},
            },
        }, req_id)

    def _handle_tools_list(self, req_id: Any) -> dict[str, Any]:
        """返回可用工具列表"""
        return jsonrpc_response({
            "tools": [
                {
                    "name": "search_articles",
                    "description": (
                        "在本地知识库中按关键词搜索 AI 技术文章，"
                        "匹配标题、摘要和标签。返回匹配文章的预览信息。"
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "搜索关键词，支持英文和中文",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "返回结果数量上限，默认 5，最大 20",
                                "default": 5,
                                "minimum": 1,
                                "maximum": 20,
                            },
                        },
                        "required": ["keyword"],
                    },
                },
                {
                    "name": "get_article",
                    "description": (
                        "根据文章 ID 获取完整内容，包括标题、摘要、来源链接、"
                        "标签、评分、发布日期等所有字段。"
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "article_id": {
                                "type": "string",
                                "description": (
                                    "文章 ID，格式如 'github-20260430-001' 或 "
                                    "'rss-20260430-001'"
                                ),
                            },
                        },
                        "required": ["article_id"],
                    },
                },
                {
                    "name": "knowledge_stats",
                    "description": (
                        "获取本地知识库统计信息，包括文章总数、来源分布、"
                        "热门标签 TOP20、平均评分、受众分布等。"
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            ],
        }, req_id)

    def _handle_tools_call(self, params: dict[str, Any],
                           req_id: Any) -> dict[str, Any]:
        """执行工具调用"""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "search_articles":
            return self._tool_search_articles(arguments, req_id)
        elif tool_name == "get_article":
            return self._tool_get_article(arguments, req_id)
        elif tool_name == "knowledge_stats":
            return self._tool_knowledge_stats(req_id)
        else:
            return jsonrpc_error(MCP_TOOL_NOT_FOUND,
                                 f"未知工具: {tool_name}", req_id)

    # ── 工具实现 ───────────────────────────────────────────────────────

    def _tool_search_articles(self, args: dict[str, Any],
                              req_id: Any) -> dict[str, Any]:
        keyword = args.get("keyword", "")
        if not keyword.strip():
            return jsonrpc_error(JSONRPC_INVALID_PARAMS,
                                 "keyword 不能为空", req_id)

        try:
            limit = min(int(args.get("limit", 5)), 20)
        except (ValueError, TypeError):
            return jsonrpc_error(JSONRPC_INVALID_PARAMS,
                                 "limit 必须为有效整数", req_id)

        results = self.kb.search(keyword, limit)
        return jsonrpc_response({
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({
                        "keyword": keyword,
                        "total_matches": len(results),
                        "articles": results,
                    }, ensure_ascii=False, indent=2),
                }
            ],
        }, req_id)

    def _tool_get_article(self, args: dict[str, Any],
                          req_id: Any) -> dict[str, Any]:
        article_id = args.get("article_id", "")
        if not article_id.strip():
            return jsonrpc_error(JSONRPC_INVALID_PARAMS,
                                 "article_id 不能为空", req_id)

        article = self.kb.get_by_id(article_id)
        if article is None:
            return jsonrpc_response({
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({
                            "error": f"未找到文章: {article_id}",
                            "found": False,
                        }, ensure_ascii=False, indent=2),
                    }
                ],
            }, req_id)

        return jsonrpc_response({
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(article, ensure_ascii=False, indent=2),
                }
            ],
        }, req_id)

    def _tool_knowledge_stats(self, req_id: Any) -> dict[str, Any]:
        stats = self.kb.stats()
        return jsonrpc_response({
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(stats, ensure_ascii=False, indent=2),
                }
            ],
        }, req_id)


# ── Stdio 传输层 ───────────────────────────────────────────────────────────

def log(message: str) -> None:
    """输出日志到 stderr，避免干扰 stdout 的 JSON-RPC 消息"""
    print(f"[mcp-server] {message}", file=sys.stderr, flush=True)


def read_message() -> dict[str, Any] | None:
    """从 stdin 读取一行 JSON-RPC 消息"""
    try:
        line = sys.stdin.readline()
        if not line:
            return None  # EOF
        return json.loads(line.strip())
    except json.JSONDecodeError as e:
        log(f"[WARN] JSON 解析失败: {e}")
        return None
    except Exception as e:
        log(f"[ERROR] 读取消息异常: {e}")
        return None


def write_message(msg: dict[str, Any]) -> None:
    """将 JSON-RPC 响应写入 stdout"""
    try:
        output = json.dumps(msg, ensure_ascii=False)
        sys.stdout.write(output + "\n")
        sys.stdout.flush()
    except Exception as e:
        log(f"[ERROR] 写入响应失败: {e}")


# ── 主循环 ─────────────────────────────────────────────────────────────────

def main():
    """MCP Server 主入口：循环读取 stdin 中的 JSON-RPC 请求并响应"""
    # 确定知识库目录：优先环境变量，否则当前目录下的 knowledge/articles
    articles_dir = os.environ.get(
        "KNOWLEDGE_ARTICLES_DIR",
        str(Path(__file__).resolve().parent / "knowledge" / "articles"),
    )

    log(f"启动 MCP Knowledge Server v1.0.0")
    log(f"知识库目录: {articles_dir}")

    # 加载知识库
    kb = KnowledgeBase(articles_dir)
    kb.load()

    server = MCPServer(kb)

    # 主循环：逐行读取 JSON-RPC 消息
    while True:
        request = read_message()
        if request is None:
            log("客户端已断开连接（EOF），退出服务")
            break

        response = server.handle(request)
        if response is not None:  # None 表示通知，不需要响应
            write_message(response)


if __name__ == "__main__":
    main()
