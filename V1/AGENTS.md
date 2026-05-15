# AGENTS.md — AI 知识库项目

> 本文件是项目的"大脑"——OpenCode 启动时自动加载，指导所有 Agent 的行为。

## 项目定义

**AI Knowledge Base（AI 知识库）** 是一个自动化技术情报收集与分析系统。
它持续追踪 GitHub Trending、Hacker News、arXiv 等来源，将分散的技术资讯
转化为结构化、可检索的知识条目。

### 核心价值
- 每日自动采集 AI/LLM/Agent 领域的高质量技术文章与开源项目
- 通过 Agent 协作完成 **采集 → 分析 → 整理** 三阶段流水线
- 输出格式统一的 JSON 知识条目，便于下游应用消费

## 项目结构

```
v1-skeleton/
├── AGENTS.md                          # 项目记忆文件（本文件）
├── .env.example                       # 环境变量模板
├── README.md                          # 使用说明
├── .opencode/
│   ├── agents/
│   │   ├── collector.md               # 采集 Agent 角色定义
│   │   ├── analyzer.md                # 分析 Agent 角色定义
│   │   └── organizer.md               # 整理 Agent 角色定义
│   └── skills/
│       ├── github-trending/SKILL.md   # GitHub Trending 采集技能
│       └── tech-summary/SKILL.md      # 技术摘要生成技能
└── knowledge/
    ├── raw/                           # 原始采集数据（JSON）
    └── articles/                      # 整理后的知识条目（JSON）
```

## 编码规范

### 文件命名
- 原始数据：`knowledge/raw/{source}-{YYYY-MM-DD}.json`
  - 例：`knowledge/raw/github-trending-2026-03-17.json`
  - 例：`knowledge/raw/hackernews-top-2026-03-17.json`
- 知识条目：`knowledge/articles/{YYYY-MM-DD}-{slug}.json`
  - 例：`knowledge/articles/2026-03-17-openai-agents-sdk.json`
- 索引文件：`knowledge/articles/index.json`

### JSON 格式
- 使用 2 空格缩进
- 日期格式：ISO 8601（`YYYY-MM-DDTHH:mm:ssZ`）
- 字符编码：UTF-8
- 每个知识条目必须包含：`id`, `title`, `source`, `url`, `collected_at`, `summary`, `tags`, `relevance_score`

### 语言约定
- 代码、JSON 键名、文件名：英文
- 摘要、分析、注释：中文
- 标签（tags）：英文小写，用连字符分隔（如 `large-language-model`）

## 工作流规则

### 三阶段流水线

```
[Collector] ──采集──→ knowledge/raw/
                          │
[Analyzer]  ──分析──→ knowledge/raw/ (enriched)
                          │
[Organizer] ──整理──→ knowledge/articles/
```

### Agent 协作规则

1. **单向数据流**：Collector → Analyzer → Organizer，不可反向
2. **职责隔离**：每个 Agent 只操作自己权限范围内的文件
3. **幂等性**：==重复运行同一天的采集不应产生重复条目==
4. **质量门控**：Analyzer 评分低于 0.6 的条目，Organizer 应丢弃
5. **可追溯**：每个条目保留 `source_url` 和 `collected_at` 用于溯源

### Agent 调用方式

在 OpenCode 中==使用 @语法调用特定 Agent：==

```
@collector 采集今天的 GitHub Trending 数据
@analyzer 分析 knowledge/raw/github-trending-2026-03-17.json
@organizer 整理今天所有已分析的原始数据
```

也可以在对话中要求主 Agent 依次委派子 Agent，实现流水线作业。

### 错误处理
- 网络请求失败时，记录错误并跳过该条目，不中断整体流程
- API 限流时，等待后重试，最多 3 次
- 数据格式异常时，写入 `knowledge/raw/errors-{date}.json` 供人工排查

## 技术栈
- **运行时**：OpenCode + LLM（DeepSeek / Qwen）
- **数据源**：GitHub API v3、Hacker News API (firebase)
- **输出格式**：JSON
- **版本管理**：Git
