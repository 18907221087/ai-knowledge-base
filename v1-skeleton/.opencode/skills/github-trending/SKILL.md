---
name: github-trending
description: When you need to collect trending GitHub repositories in AI/LLM/Agent domains
---

# GitHub Trending 采集技能

## 触发场景

当用户要求采集 GitHub 上 AI/LLM/Agent 相关的热门仓库时，自动激活此技能。

## 采集步骤

### 1. 构造搜索请求

使用 GitHub Search API 搜索最近 7 天内的热门仓库：

```
GET https://api.github.com/search/repositories
```

**查询参数**：
- `q`: 组合以下关键词（OR 连接）：
  - `AI`, `LLM`, `"large language model"`, `agent`, `RAG`
  - `MCP`, `"model context protocol"`, `"agentic"`
  - 加上时间过滤：`created:>{7天前的日期}` 或 `pushed:>{7天前的日期}`
- `sort`: `stars`
- `order`: `desc`
- `per_page`: `30`

**请求头**：
```
Accept: application/vnd.github.v3+json
Authorization: Bearer ${GITHUB_TOKEN}
```

### 2. 过滤结果

从返回的仓库中，按以下条件过滤：

- Star 数 >= 50（过滤掉低质量仓库）
- 有英文 description（无描述的仓库通常质量较低）
- 非 fork 仓库（`fork: false`）
- 排除以下类型：awesome-list（纯链接集合）、课程作业、个人笔记

### 3. 提取元数据

对每个通过过滤的仓库，提取以下信息：

```json
{
  "id": "{owner}/{repo}",
  "title": "{repo name}",
  "description": "{repo description}",
  "url": "{html_url}",
  "stars": "{stargazers_count}",
  "forks": "{forks_count}",
  "language": "{language}",
  "topics": ["{topics array}"],
  "license": "{license.spdx_id}",
  "created_at": "{created_at}",
  "updated_at": "{pushed_at}",
  "open_issues": "{open_issues_count}"
}
```

### 4. 增强信息（可选）

对 Star 数 Top 5 的仓库，额外获取 README 内容：

```
GET https://api.github.com/repos/{owner}/{repo}/readme
Accept: application/vnd.github.v3.raw
```

将 README 的前 500 字存入 `readme_excerpt` 字段，用于后续 Analyzer 生成更准确的摘要。

### 5. 输出

将采集结果保存为 JSON 文件：

- 文件路径：`knowledge/raw/github-trending-{YYYY-MM-DD}.json`
- 顶层包含 `source`, `collected_at`, `query`, `count`, `items`
- 使用 2 空格缩进

## 错误处理

| 错误 | 处理方式 |
|------|----------|
| HTTP 401 | 检查 GITHUB_TOKEN 是否设置 |
| HTTP 403 (rate limit) | 读取 `X-RateLimit-Reset`，报告剩余等待时间 |
| HTTP 422 (bad query) | 简化查询条件后重试 |
| 网络超时 | 等待 5 秒后重试，最多 3 次 |

## 质量标准

- 采集条目数：15-30 条为正常范围
- 少于 10 条：关键词可能需要扩展，报告给用户
- 多于 50 条：过滤条件可能太宽松，提高 Star 阈值
