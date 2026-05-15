---
name: format-output
description: 当用户要求整理文章格式、去重、校验质量时触发
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
---

# 格式化输出 Skill

## 触发条件

用户提到以下意图时激活：
- "整理"、"格式化" 文章
- "去重"、"检查重复"
- "校验"、"质量检查"

## 执行步骤

1. 读取 `knowledge/articles/` 中的文章
2. 检查必填字段完整性
3. 运行校验脚本：
   ```bash
   python hooks/validate_json.py knowledge/articles/*.json
   python hooks/check_quality.py knowledge/articles/*.json
   ```
4. 修复格式问题，标记不合格文章

## 质量标准

- 所有必填字段不为空
- ID 格式正确：`{source}-{YYYYMMDD}-{NNN}`
- 评分在 1-10 范围内
- 摘要不少于 20 字
- 至少包含 1 个标签
- 质量评分 >= B 级（60 分）
