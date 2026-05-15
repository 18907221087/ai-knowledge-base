---
name: collect-articles
description: 当用户要求采集AI文章、搜索技术内容、获取GitHub热门项目时触发
allowed-tools:
  - Bash
  - Read
  - Write
  - Glob
  - WebFetch
---

# 采集文章 Skill

## 触发条件

用户提到以下意图时激活：
- "采集"、"收集"、"搜索" AI 相关内容
- "获取 GitHub 热门项目"
- "抓取 RSS 订阅"

## 执行步骤

1. 确认采集参数：渠道（github/rss）、关键词、数量限制
2. 调用 pipeline 脚本执行采集：
   ```bash
   python pipeline/pipeline.py --sources github --limit 10
   ```
3. 检查采集结果，汇报采集数量和关键内容

## 输出位置

- 原始数据：`knowledge/raw/`
- 处理后文章：`knowledge/articles/`
