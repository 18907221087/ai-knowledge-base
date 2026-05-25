---
name: analyze-content
description: 当用户要求分析文章技术价值、生成摘要、进行评分时触发
allowed-tools:
  - Read
  - Write
  - Glob
  - Grep
---

# 分析内容 Skill

## 触发条件

用户提到以下意图时激活：
- "分析"、"评估" 文章或项目
- "生成摘要"、"打分"
- "对比" 多个技术方案

## 分析框架

对每篇文章从五个维度分析：

1. **核心创新** — 这篇内容解决了什么问题？有什么新方法？
2. **技术深度** — 是浅层介绍还是深度实现？
3. **实用价值** — 读者能直接应用吗？
4. **时效性** — 内容是否最新？会很快过时吗？
5. **生态影响** — 对 AI 工具链/框架生态有什么影响？

## 输出格式

```json
{
  "summary": "简洁的技术摘要",
  "score": 8,
  "tags": ["relevant", "tags"],
  "audience": "beginner/intermediate/advanced",
  "analysis_note": "分析师备注"
}
```
