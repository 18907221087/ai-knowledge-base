---
name: tech-summary
description: When you need to analyze and summarize collected tech articles
---

# 技术摘要生成技能

## 触发场景

当用户要求对已采集的技术文章或开源项目生成分析摘要时，自动激活此技能。

## 摘要生成流程

### 1. 读取源数据

从 `knowledge/raw/` 读取目标 JSON 文件，提取每个条目的以下信息：
- `title` — 标题
- `description` — 描述
- `url` — 链接（用于获取更多上下文）
- `stars` / `score` — 热度指标
- `readme_excerpt` — README 摘录（如有）

### 2. 获取补充上下文（可选）

如果条目没有 `readme_excerpt` 且 `url` 可用：
- GitHub 仓库：通过 API 获取 README 前 500 字
- 博客/文章：通过 WebFetch 获取正文前 1000 字
- 获取失败不阻塞流程，基于已有信息生成摘要

### 3. 生成中文技术摘要

**摘要长度**：100-200 个中文字符

**结构要求**（不需要显式标注，自然融入）：
1. **定位**（1 句）：这个项目/文章解决什么问题
2. **核心内容**（2-3 句）：关键技术方案、架构特点、主要创新
3. **价值判断**（1 句）：对 AI 工程师的实际意义

**写作规范**：
- 第一句直接点明核心，不要 "本项目是..."、"这篇文章介绍了..." 等模板开头
- 技术术语保留英文原文，如 RAG、MCP、Fine-tuning
- 避免空洞的形容词（"强大的"、"创新性的"）——用具体信息替代
- 如果能写出具体数字（性能提升、模型大小等），优先使用数字

**示例**：

好的摘要：
> 基于 Tree-of-Thought 推理框架，让 LLM 在复杂数学推理任务上的准确率从
> 54% 提升到 74%。核心思路是将单次推理拆分为多步搜索树，每步生成多个候选
> 并通过 LLM 自评估剪枝。实现代码不到 500 行 Python，可直接集成到现有
> LangChain 管道中。

差的摘要：
> 这是一个非常创新的项目，使用了先进的 AI 技术来提升推理能力。
> 它采用了一种新颖的方法，在多个基准测试中取得了很好的效果。
> 对于 AI 从业者来说值得关注。

### 4. 评分

按 AGENTS.md 中定义的 5 维度评分体系打分：

| 维度 | 权重 | 评分要点 |
|------|------|----------|
| 技术深度 | 0.25 | 有原理说明 > 只有使用方法 > 纯新闻报道 |
| 实用价值 | 0.30 | 可直接用 > 需大量适配 > 纯学术 |
| 时效性 | 0.20 | 本周发布 > 本月发布 > 更早 |
| 社区热度 | 0.15 | GitHub: >1K Stars 高, >100 中, <100 低; HN: >200 高, >50 中 |
| 领域匹配 | 0.10 | Agent/LLM 核心 > AI 相关 > 泛技术 |

### 5. 提取标签

为每个条目生成 3-5 个标签：

**标签词库**（优先使用，保持一致性）：
- 领域：`large-language-model`, `agent-framework`, `rag`, `mcp`, `fine-tuning`, `prompt-engineering`, `multi-agent`, `code-generation`
- 技术：`transformer`, `attention`, `embedding`, `vector-database`, `knowledge-graph`
- 工具：`langchain`, `llamaindex`, `openai`, `anthropic`, `deepseek`, `huggingface`
- 场景：`chatbot`, `code-assistant`, `data-analysis`, `document-qa`, `workflow-automation`

如果条目涉及词库中没有的概念，可以新增标签，但必须遵循小写连字符格式。

### 6. 输出格式

对每个条目追加以下字段：

```json
{
  "summary": "中文技术摘要...",
  "relevance_score": 0.85,
  "score_breakdown": {
    "tech_depth": 0.80,
    "practical_value": 0.90,
    "timeliness": 0.85,
    "community_heat": 0.80,
    "domain_match": 0.90
  },
  "tags": ["agent-framework", "python", "openai"],
  "analyzed_at": "2026-03-17T11:00:00Z"
}
```

## 批量处理

当一个文件中包含多个条目时：
- 逐条处理，每条独立评分
- 不要因为前面的条目分数高就压低后面的（绝对评分，非相对排名）
- 处理完所有条目后再统一输出
