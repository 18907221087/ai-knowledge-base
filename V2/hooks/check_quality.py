#!/usr/bin/env python3
"""
质量评分脚本 — 五维度评估文章质量。

五个维度（加权总分 100 分）：
  1. 摘要质量   — 25 分
  2. 技术深度   — 25 分
  3. 格式规范   — 20 分
  4. 标签精度   — 15 分
  5. 空洞词检测 — 15 分

等级：A (>=80) / B (>=60) / C (<60)

用法：
    python hooks/check_quality.py knowledge/articles/github-20260317-001.json
    python hooks/check_quality.py knowledge/articles/*.json

退出码：
    0 — 全部 B 级以上
    1 — 存在 C 级文章
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ── 空洞词列表 ───────────────────────────────────────────────────────────

HOLLOW_WORDS_ZH = [
    "赋能", "抓手", "闭环", "打通", "全链路", "底层逻辑",
    "颗粒度", "对齐", "拉通", "沉淀", "强大的", "革命性的",
]

HOLLOW_WORDS_EN = [
    "groundbreaking", "revolutionary", "game-changing", "cutting-edge",
    "state-of-the-art", "leverage", "synergy", "paradigm shift",
    "disruptive", "next-generation", "world-class",
]

HOLLOW_WORDS = HOLLOW_WORDS_ZH + HOLLOW_WORDS_EN

# ── 合法标签列表 ─────────────────────────────────────────────────────────

VALID_TAGS = {
    "agent", "rag", "mcp", "llm", "fine-tuning", "prompt-engineering",
    "multi-agent", "tool-use", "evaluation", "deployment", "security",
    "reasoning", "code-generation", "vision", "audio", "robotics",
}


# ── 评分结构 ─────────────────────────────────────────────────────────────

@dataclass
class DimensionScore:
    """单维度评分"""
    name: str
    score: float
    max_score: float
    details: str

    @property
    def percentage(self) -> float:
        return (self.score / self.max_score * 100) if self.max_score > 0 else 0


@dataclass
class QualityReport:
    """质量评估报告"""
    filepath: str
    dimensions: list[DimensionScore]

    @property
    def total_score(self) -> float:
        return sum(d.score for d in self.dimensions)

    @property
    def max_total(self) -> float:
        return sum(d.max_score for d in self.dimensions)

    @property
    def grade(self) -> str:
        score = self.total_score
        if score >= 80:
            return "A"
        elif score >= 60:
            return "B"
        else:
            return "C"


# ── 五维度评分函数 ───────────────────────────────────────────────────────

def score_summary_quality(data: dict[str, Any]) -> DimensionScore:
    """
    维度 1：摘要质量（25 分）

    评分规则：
    - 有摘要且长度 >= 50 字：20 分
    - 有摘要且长度 >= 20 字：15 分
    - 有摘要但太短：5 分
    - 无摘要：0 分
    - 包含技术关键词（+5 分）
    """
    max_score = 25.0
    summary = data.get("summary", "").strip()

    if not summary:
        return DimensionScore("摘要质量", 0, max_score, "无摘要")

    # 基础分
    length = len(summary)
    if length >= 50:
        base = 20.0
        detail = f"长度充足 ({length} 字)"
    elif length >= 20:
        base = 15.0
        detail = f"长度基本 ({length} 字)"
    else:
        base = 5.0
        detail = f"太短 ({length} 字)"

    # 技术关键词奖励
    tech_keywords = [
        "模型", "训练", "推理", "API", "框架", "agent", "LLM", "RAG",
        "token", "向量", "embedding", "transformer", "微调",
        "model", "training", "inference", "framework",
    ]
    keyword_count = sum(1 for kw in tech_keywords if kw.lower() in summary.lower())
    bonus = min(5.0, keyword_count * 1.0)
    if bonus > 0:
        detail += f", 含 {keyword_count} 个技术关键词"

    score = min(max_score, base + bonus)
    return DimensionScore("摘要质量", score, max_score, detail)


def score_tech_depth(data: dict[str, Any]) -> DimensionScore:
    """
    维度 2：技术深度（25 分）

    基于文章 score 字段映射。
    """
    max_score = 25.0
    article_score = data.get("score", 5)

    if not isinstance(article_score, (int, float)):
        return DimensionScore("技术深度", 10, max_score, "score 字段类型异常")

    # 将 1-10 的 score 映射到 0-25
    mapped = (article_score / 10) * max_score
    detail = f"文章评分 {article_score}/10 → {mapped:.1f}/{max_score}"

    return DimensionScore("技术深度", round(mapped, 1), max_score, detail)


def score_format(data: dict[str, Any]) -> DimensionScore:
    """
    维度 3：格式规范（20 分）

    检查项：
    - 有 id (+4)
    - 有 title (+4)
    - 有 source_url (+4)
    - 有 status (+4)
    - 有 updated_at 或 collected_at (+4)
    """
    max_score = 20.0
    score = 0.0
    checks: list[str] = []

    field_checks = [
        ("id", 4),
        ("title", 4),
        ("source_url", 4),
        ("status", 4),
    ]

    for field_name, points in field_checks:
        val = data.get(field_name, "")
        if val and str(val).strip():
            score += points
        else:
            checks.append(f"缺少 {field_name}")

    # 时间戳
    if data.get("updated_at") or data.get("collected_at"):
        score += 4
    else:
        checks.append("缺少时间戳")

    detail = "完整" if not checks else "缺失: " + ", ".join(checks)
    return DimensionScore("格式规范", score, max_score, detail)


def score_tags(data: dict[str, Any]) -> DimensionScore:
    """
    维度 4：标签精度（15 分）

    评分规则：
    - 有 1-3 个合法标签：15 分
    - 有标签但不在合法列表：10 分
    - 标签过多 (>5)：扣分
    - 无标签：0 分
    """
    max_score = 15.0
    tags = data.get("tags", [])

    if not tags:
        return DimensionScore("标签精度", 0, max_score, "无标签")

    valid_count = sum(1 for t in tags if t in VALID_TAGS)
    total_count = len(tags)

    if 1 <= total_count <= 3 and valid_count == total_count:
        score = 15.0
        detail = f"{total_count} 个标签，全部合法"
    elif valid_count > 0:
        score = 10.0
        detail = f"{valid_count}/{total_count} 个合法标签"
    else:
        score = 5.0
        detail = f"有 {total_count} 个标签但均不在标准列表"

    if total_count > 5:
        penalty = min(5.0, (total_count - 5) * 1.0)
        score = max(0, score - penalty)
        detail += f", 标签过多 (扣 {penalty} 分)"

    return DimensionScore("标签精度", score, max_score, detail)


def score_hollow_words(data: dict[str, Any]) -> DimensionScore:
    """
    维度 5：空洞词检测（15 分）

    摘要和标题中每出现一个空洞词，扣 3 分。
    """
    max_score = 15.0
    text = (data.get("summary", "") + " " + data.get("title", "")).lower()

    found: list[str] = []
    for word in HOLLOW_WORDS:
        if word.lower() in text:
            found.append(word)

    penalty = min(max_score, len(found) * 3.0)
    score = max_score - penalty

    if found:
        detail = f"发现 {len(found)} 个空洞词: {', '.join(found[:5])}"
    else:
        detail = "未发现空洞词"

    return DimensionScore("空洞词检测", score, max_score, detail)


# ── 综合评估 ─────────────────────────────────────────────────────────────

def evaluate_quality(filepath: str, data: dict[str, Any]) -> QualityReport:
    """
    对单篇文章进行五维度综合评估。

    Args:
        filepath: 文件路径
        data: 文章 JSON 数据

    Returns:
        质量评估报告
    """
    dimensions = [
        score_summary_quality(data),
        score_tech_depth(data),
        score_format(data),
        score_tags(data),
        score_hollow_words(data),
    ]

    return QualityReport(filepath=filepath, dimensions=dimensions)


def print_report(report: QualityReport) -> None:
    """格式化输出评估报告"""
    print(f"\n{'─'*50}")
    print(f"文件: {report.filepath}")
    print(f"{'─'*50}")

    for d in report.dimensions:
        bar_len = int(d.percentage / 5)  # 20 格满分
        bar = "█" * bar_len + "░" * (20 - bar_len)
        print(f"  {d.name:8s} [{bar}] {d.score:5.1f}/{d.max_score:.0f}  {d.details}")

    grade_emoji = {"A": "🟢", "B": "🟡", "C": "🔴"}
    emoji = grade_emoji.get(report.grade, "")
    print(f"\n  总分: {report.total_score:.1f}/{report.max_total:.0f}  "
          f"等级: {emoji} {report.grade}")


# ── CLI 入口 ─────────────────────────────────────────────────────────────

def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python hooks/check_quality.py <json_file> [json_file2 ...]")
        print("示例: python hooks/check_quality.py knowledge/articles/*.json")
        return 1

    files = sys.argv[1:]
    total_files = 0
    grade_counts = {"A": 0, "B": 0, "C": 0}
    has_c_grade = False

    for filepath in files:
        path = Path(filepath)
        if not path.exists() or path.suffix != ".json":
            continue

        total_files += 1

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"[ERROR] {filepath}: JSON 解析失败 — {e}")
            has_c_grade = True
            continue

        report = evaluate_quality(filepath, data)
        print_report(report)
        grade_counts[report.grade] = grade_counts.get(report.grade, 0) + 1

        if report.grade == "C":
            has_c_grade = True

    # 汇总
    print(f"\n{'='*50}")
    print(f"质量评估汇总: {total_files} 文件")
    print(f"  A 级 (>=80): {grade_counts.get('A', 0)}")
    print(f"  B 级 (>=60): {grade_counts.get('B', 0)}")
    print(f"  C 级 (<60):  {grade_counts.get('C', 0)}")
    print(f"{'='*50}")

    return 1 if has_c_grade else 0


if __name__ == "__main__":
    sys.exit(main())
