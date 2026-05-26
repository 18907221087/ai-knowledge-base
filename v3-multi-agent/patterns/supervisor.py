"""
Supervisor 模式 — 主管 Agent 协调多个工人 Agent

Supervisor 模式的核心思想:
1. 一个 Supervisor Agent 负责任务分解和调度（像项目经理）
2. 多个 Worker Agent 各自完成子任务（像团队成员）
3. Supervisor 汇总结果并做最终决策

执行流程:
  用户任务 → Supervisor.plan() 分解 → Supervisor.execute() 逐个调度
  → Collector → Analyzer → Reviewer → Supervisor._summarize() → 最终报告

与 Router 模式的区别:
- Router:   1对1 分发（一个请求 → 一个处理器，路由完就结束）
- Supervisor: 1对多 协调（一个任务 → 多个工人 → 汇总，有依赖关系）

适用场景: 需要多步骤协作的复杂任务，如"采集 + 分析 + 审核"流水线"""

import json
from dataclasses import dataclass, field

# 导入 LLM 调用工具
# - chat():      普通对话，返回自然语言
# - chat_json(): 返回 JSON 结构化数据（用于工人与 Supervisor 之间的结构化通信）
# - accumulate_usage(): 累计多次调用的 Token 用量和费用
from workflows.model_client import accumulate_usage, chat, chat_json


# =============================================================================
# Worker 定义 — 每个 Worker 是流水线上的一个节点
#
# 所有 Worker 遵循统一协议:
# - 入参: task (dict) — 由 Supervisor 指定的子任务参数
# - 返回: WorkerResult — 统一的结果容器
#
# 当前定义了 3 个 Worker:
#   collector → analyzer → reviewer（按依赖顺序）
# =============================================================================

@dataclass
class WorkerResult:
    """工人 Agent 的执行结果（统一数据结构）

    使用 dataclass 而非普通 dict 的好处:
    - 类型安全，IDE 有自动补全
    - 默认值通过 field(default_factory=dict) 避免可变默认值陷阱
    - 统一了成功和失败的返回格式，Supervisor 无需 if-else 判断不同结构

    Attributes:
        worker_name: 工人名称（collector/analyzer/reviewer）
        status:      执行状态（"success" 或 "error"）
        data:        执行结果数据（格式由具体 Worker 定义）
        usage:       Token 用量记录，用于累计成本
    """
    worker_name: str
    status: str  # "success" | "error"
    data: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)


# --- Worker 1: 采集 ---

def collector_worker(task: dict) -> WorkerResult:
    """采集工人：根据 Supervisor 指令采集特定来源的数据

    职责: 从指定来源（GitHub/HN/arXiv）按关键词搜索技术内容
    这是流水线的第一步，输出数据供 analyzer 消费

    Args:
        task: Supervisor 分配的子任务
            {
                "source": "github" | "hackernews" | "arxiv",
                "keywords": ["AI", "agent"],
                "limit": 5
            }

    Returns:
        WorkerResult，成功时 data 含 items 列表和 source 来源
    """
    # 解构任务参数，提供默认值防止 KeyError
    source = task.get("source", "github")
    keywords = task.get("keywords", ["AI", "agent"])
    limit = task.get("limit", 5)

    # 构造 prompt，让 LLM 模拟采集过程
    # 实际项目可将此处替换为真实 API 调用（GitHub API / RSS / ArXiv）
    prompt = f"""请模拟从 {source} 采集关于 {', '.join(keywords)} 的技术资讯。
返回 JSON 数组，每条包含 title, url, description, source 字段。
最多返回 {limit} 条。"""

    try:
        # chat_json() 保证返回的是可解析的 JSON（非 JSON 会重试）
        result, usage = chat_json(prompt)
        # 兼容 LLM 返回单条 dict 或列表
        items = result if isinstance(result, list) else [result]
        return WorkerResult(
            worker_name="collector",
            status="success",
            data={"items": items, "source": source},
            usage=usage,
        )
    except Exception as e:
        # 统一异常处理：不抛出异常，而是返回 error 状态的 Result
        # 这样 Supervisor 无需 try-catch，只需检查 status 字段
        return WorkerResult(
            worker_name="collector",
            status="error",
            data={"error": str(e)},
        )


# --- Worker 2: 分析 ---

def analyzer_worker(task: dict) -> WorkerResult:
    """分析工人：对给定数据进行深度分析

    职责: 接收上游 collector 采集的 items，按指定类型进行分析
    这是流水线的第二步，依赖 collector 的输出

    Args:
        task: Supervisor 分配的子任务
            {
                "items": [{title, url, description, source}, ...],
                "analysis_type": "summary" | "trend" | "comparison"
            }

    Returns:
        WorkerResult，成功时 data 含 analysis_type, findings, summary, confidence
    """
    items = task.get("items", [])
    analysis_type = task.get("analysis_type", "summary")

    # 将 items 序列化后嵌入 prompt，让 LLM 逐条分析
    prompt = f"""请对以下技术资讯进行 {analysis_type} 分析:

{json.dumps(items, ensure_ascii=False, indent=2)}

返回 JSON 格式:
{{
    "analysis_type": "{analysis_type}",
    "findings": ["发现1", "发现2", "发现3"],   // 关键发现列表
    "summary": "200字以内的分析总结",
    "confidence": 0.85                          // 置信度 0~1
}}"""

    try:
        result, usage = chat_json(prompt)
        return WorkerResult(
            worker_name="analyzer",
            status="success",
            data=result if isinstance(result, dict) else {"raw": result},
            usage=usage,
        )
    except Exception as e:
        return WorkerResult(
            worker_name="analyzer",
            status="error",
            data={"error": str(e)},
        )


# --- Worker 3: 审核 ---

def reviewer_worker(task: dict) -> WorkerResult:
    """审核工人：对分析结果进行质量审核

    职责: 接收 analyzer 的分析结论，用 LLM 二次评估其质量
    这是流水线的第三步（最后一步），起到质量把关的作用

    Args:
        task: Supervisor 分配的子任务
            {
                "analyses": [分析结果 dict, ...],
                "criteria": "准确性、深度、实用性"  // 审核维度，逗号分隔
            }

    Returns:
        WorkerResult，成功时 data 含 approved, score, issues, suggestions
    """
    analyses = task.get("analyses", [])
    criteria = task.get("criteria", "准确性、深度、实用性")

    # 构造 prompt 让 LLM 以审核员身份评判上游分析结果
    prompt = f"""请审核以下分析结果，评估维度: {criteria}

{json.dumps(analyses, ensure_ascii=False, indent=2)}

返回 JSON 格式:
{{
    "approved": true或false,              // 是否批准通过
    "score": 4.2,                         // 评分 0~5
    "issues": ["问题1（如有）"],          // 发现的问题
    "suggestions": ["改进建议1（如有）"]   // 改进建议
}}"""

    try:
        result, usage = chat_json(prompt)
        return WorkerResult(
            worker_name="reviewer",
            status="success",
            data=result if isinstance(result, dict) else {"raw": result},
            usage=usage,
        )
    except Exception as e:
        return WorkerResult(
            worker_name="reviewer",
            status="error",
            data={"error": str(e)},
        )


# Worker 注册表 — 所有工人在此注册
# Supervisor 通过 worker_name 查找对应的 Worker 函数
# 新增 Worker 只需: 1) 写函数 2) 在这里加一行 3) 更新 Supervisor 的 plan prompt
WORKERS = {
    "collector": collector_worker,
    "analyzer": analyzer_worker,
    "reviewer": reviewer_worker,
}


# =============================================================================
# Supervisor 核心 — 任务规划 + 调度执行 + 结果汇总
#
# Supervisor 是整个模式的大脑，它不知道 Worker 的实现细节，
# 只知道每个 Worker 的名称、能力描述和输入格式。
# 这种"声明式调度"的好处是 Worker 可以独立替换，互不影响。
# =============================================================================

class Supervisor:
    """主管 Agent：分解任务、调度工人、汇总结果

    职责边界:
    - plan():      将用户自然语言任务 → LLM 分解为结构化步骤计划
    - execute():   按计划逐步骤调度 Worker，自动处理数据依赖传递
    - _summarize():将所有步骤结果汇总为最终报告

    执行流程示意图:
    ┌─────────────────────────────────────────────────┐
    │ plan("采集并分析AI Agent进展")                    │
    │   ↓                                              │
    │ [{step:1, worker:collector},                     │
    │  {step:2, worker:analyzer, depends_on:[1]},      │
    │  {step:3, worker:reviewer, depends_on:[2]}]      │
    │                                                   │
    │ execute()                                         │
    │   step 1: collector_worker(task) → items          │
    │   step 2: 注入 step1 的 items → analyzer → finds  │
    │   step 3: 注入 step2 的 data → reviewer → score   │
    │                                                   │
    │ _summarize() → 最终报告                           │
    └─────────────────────────────────────────────────┘
    """

    def __init__(self) -> None:
        """初始化 Supervisor

        cost_tracker:  累计 Token 用量和费用（贯穿整个工作流）
                      使用 accumulate_usage() 函数增量合并，
                      最终可算出本次任务的总花费
        execution_log: 执行日志，记录每一步的 worker 名和执行状态
                      用于调试和审计
        """
        self.cost_tracker: dict = {}
        self.execution_log: list[dict] = []

    def plan(self, task_description: str) -> list[dict]:
        """任务规划：将高层任务分解为工人子任务

        这是 Supervisor 模式的核心能力——自动任务分解。
        它用 LLM 理解用户意图，规划出合理的执行顺序和依赖关系。

        设计考量:
        - prompt 中明确列出了每个 Worker 的能力和所需参数，
          这样 LLM 能精确地构造 task dict，不会遗漏必要字段
        - 指定 `depends_on` 机制确保数据流正确（先采集才能分析）
        - 规划失败时有默认降级计划，保证系统不因 LLM 异常而崩溃

        Args:
            task_description: 用户的任务描述（自然语言）

        Returns:
            子任务计划列表，每个元素包含 step, worker, task, depends_on
            示例:
            [
                {"step": 1, "worker": "collector", "task": {"source": "github", ...}, "depends_on": []},
                {"step": 2, "worker": "analyzer",  "task": {"items": [], ...},      "depends_on": [1]},
            ]
        """
        # 构造规划 prompt: 告诉 LLM 有哪些可用工人及其能力边界
        prompt = f"""你是任务调度主管。请将以下任务分解为子任务并分配给工人。

任务: {task_description}

可用工人:
- collector: 数据采集（需要 source, keywords, limit 参数）
- analyzer: 数据分析（需要 items, analysis_type 参数）
- reviewer: 质量审核（需要 analyses, criteria 参数）

请返回 JSON 数组，每个元素格式:
{{
    "step": 1,                                   // 步骤序号
    "worker": "collector",                       // 指派的工人名
    "task": {{"source": "github", "keywords": ["agent"], "limit": 5}},  // 子任务参数
    "depends_on": []                             // 依赖的前置步骤编号
}}

注意:
- 按执行顺序排列
- depends_on 填写依赖的步骤编号（如 analyzer 依赖 collector 的输出）
- 确保数据流合理（先采集，再分析，最后审核）"""

        try:
            # chat_json() 保证返回可解析的 JSON 数组
            result, usage = chat_json(
                prompt,
                system="你是严谨的任务调度主管。返回可执行的子任务计划。",
            )
            # 累计此次 LLM 调用的 Token 费用到 tracker
            self.cost_tracker = accumulate_usage(self.cost_tracker, usage)

            # 兼容单条 dict 的返回格式
            plan = result if isinstance(result, list) else [result]
            print(f"[Supervisor] 规划了 {len(plan)} 个子任务")
            return plan

        except Exception as e:
            # 规划失败不崩溃，使用硬编码的默认 3 步计划作为降级方案
            print(f"[Supervisor] 规划失败: {e}，使用默认计划")
            return [
                {
                    "step": 1,
                    "worker": "collector",
                    "task": {"source": "github", "keywords": ["AI", "agent"], "limit": 5},
                    "depends_on": [],
                },
                {
                    "step": 2,
                    "worker": "analyzer",
                    "task": {"items": [], "analysis_type": "summary"},
                    "depends_on": [1],  # 依赖步骤 1 的输出
                },
                {
                    "step": 3,
                    "worker": "reviewer",
                    "task": {"analyses": [], "criteria": "准确性、深度"},
                    "depends_on": [2],  # 依赖步骤 2 的输出
                },
            ]

    def execute(self, task_description: str) -> dict:
        """执行完整的 Supervisor 工作流

        这是对外的主要接口，一次调用完成:
        规划 → 逐步执行（含依赖注入） → 汇总

        数据依赖传递机制:
        - executor 遍历步骤时，检查 depends_on 列表
        - 如果某个前置步骤已完成，自动将其结果注入到当前步骤的 task 中
        - 具体映射: 上游 items → 下游 items, 上游 findings → 下游 analyses

        Args:
            task_description: 用户的任务描述（自然语言）

        Returns:
            最终报告 dict，包含:
            - task:          原始任务
            - summary:       LLM 生成的汇总文本
            - step_results:  各步骤的详细结果
            - execution_log: 执行日志
            - cost_tracker:  Token 用量和费用统计
        """
        # Step 1: 调用 LLM 将自然语言任务分解为结构化步骤计划
        plan = self.plan(task_description)

        # Step 2: 按计划逐步执行，处理 Worker 间的数据依赖
        step_results: dict[int, WorkerResult] = {}

        for step_def in plan:
            step_num = step_def["step"]
            worker_name = step_def["worker"]
            task = step_def["task"]

            # ---- 依赖注入: 将上游输出自动填入下游输入 ----
            # 例如 step2 (analyzer) 依赖 step1 (collector)，
            # 则自动把 collector 返回的 items 填入 analyzer 的 task["items"]
            for dep_step in step_def.get("depends_on", []):
                if dep_step in step_results:
                    dep_result = step_results[dep_step]
                    if dep_result.status == "success":
                        dep_data = dep_result.data
                        # 映射规则: 上游 items → 下游 items
                        if "items" in dep_data and "items" in task:
                            task["items"] = dep_data["items"]
                        # 映射规则: 上游 findings → 下游 analyses
                        if "findings" in dep_data and "analyses" in task:
                            task["analyses"] = [dep_data]
                    else:
                        # 上游失败时记录警告但不阻断，允许降级执行
                        print(f"[Supervisor] 步骤 {dep_step} 失败，"
                              f"步骤 {step_num} 将在无上游数据的情况下执行")

            # ---- 查找并调用 Worker ----
            worker = WORKERS.get(worker_name)
            if not worker:
                # Worker 名不存在（如 LLM 生成了未知的 worker 名）
                print(f"[Supervisor] 未知工人: {worker_name}，跳过")
                continue

            print(f"[Supervisor] 步骤 {step_num}: 调度 {worker_name}")
            result = worker(task)
            step_results[step_num] = result

            # 将 Worker 调用的 Token 用量合并到总 tracker
            if result.usage:
                self.cost_tracker = accumulate_usage(
                    self.cost_tracker, result.usage
                )

            # 记录执行日志（用于最终报告和调试）
            self.execution_log.append({
                "step": step_num,
                "worker": worker_name,
                "status": result.status,  # success / error
            })

        # Step 3: 收集所有步骤结果，用 LLM 生成最终汇总报告
        return self._summarize(task_description, step_results)

    def _summarize(
        self, task_description: str, results: dict[int, WorkerResult]
    ) -> dict:
        """汇总所有工人的结果，生成最终报告

        This is the "glue" step of the Supervisor pattern — taking
        heterogeneous results from multiple workers and synthesizing
        them into a coherent final output for the user.

        Args:
            task_description: 原始任务描述
            results:          step_num → WorkerResult 的映射

        Returns:
            最终报告 dict，供调用方展示或持久化
        """
        # 将 WorkerResult 对象转为纯 dict，便于 JSON 序列化后发送给 LLM
        all_data = {
            step: {
                "worker": r.worker_name,
                "status": r.status,
                "data": r.data,
            }
            for step, r in results.items()
        }

        # 构造汇总 prompt: 告诉 LLM 原始任务 + 各步骤结果
        prompt = f"""请汇总以下工作成果为最终报告。

原始任务: {task_description}

各步骤结果:
{json.dumps(all_data, ensure_ascii=False, indent=2)}

请返回简洁的中文汇总报告（200字以内）。"""

        # 调用 LLM 生成汇总（用 chat 而非 chat_json，因为汇总就是自然语言）
        summary, usage = chat(prompt, system="你是报告撰写专家。简洁、有条理。")
        self.cost_tracker = accumulate_usage(self.cost_tracker, usage)

        # 组装最终返回结构
        return {
            "task": task_description,
            "summary": summary,             # LLM 生成的汇总文本
            "step_results": all_data,        # 各步骤的详细结果
            "execution_log": self.execution_log,  # 执行过程日志
            "cost_tracker": self.cost_tracker,    # Token 用量和费用
        }


# --- 命令行测试入口 ---
if __name__ == "__main__":
    import sys

    # 从命令行参数获取任务，无参数时使用默认任务
    # 用法: python patterns/supervisor.py "对比 PyTorch 和 JAX"
    task = (
        " ".join(sys.argv[1:])
        if len(sys.argv) > 1
        else "采集并分析今天的 AI Agent 领域最新进展"
    )
    print(f"任务: {task}\n")

    # 实例化 Supervisor 并执行完整工作流
    supervisor = Supervisor()
    report = supervisor.execute(task)

    print("\n" + "=" * 60)
    print("最终报告:")
    print(report["summary"])
    print(f"\n总成本: ¥{report['cost_tracker'].get('total_cost_yuan', 0)}")
