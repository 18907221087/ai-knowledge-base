#!/usr/bin/env python3
"""
JSON 格式校验脚本 — 检查知识库文章是否符合标准格式。

用法：
    python hooks/validate_json.py knowledge/articles/github-20260317-001.json
    python hooks/validate_json.py knowledge/articles/*.json

退出码：
    0 — 全部通过
    1 — 存在校验失败
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

# ── 校验规则 ─────────────────────────────────────────────────────────────

# 必填字段及其类型
REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

# ID 格式：{source}-{YYYYMMDD}-{NNN}
ID_PATTERN = re.compile(r"^[a-z][\w:-]+-\d{8}-\d{3}$")

# 合法的 status 值
VALID_STATUSES = {"draft", "review", "published", "archived"}

# score 范围
SCORE_MIN = 1
SCORE_MAX = 10

# URL 基本格式
URL_PATTERN = re.compile(r"^https?://\S+$")

# 摘要最小长度（字符数）
SUMMARY_MIN_LENGTH = 20

# 合法的 audience 值
VALID_AUDIENCES = {"beginner", "intermediate", "advanced"}


# ── 校验函数 ─────────────────────────────────────────────────────────────

def validate_article(data: dict[str, Any]) -> list[str]:
    """
    校验单篇文章，返回错误列表。

    Args:
        data: 文章 JSON 数据

    Returns:
        错误消息列表，空列表表示校验通过
    """
    errors: list[str] = []

    # 检查必填字段
    for field_name, field_type in REQUIRED_FIELDS.items():
        if field_name not in data:
            errors.append(f"缺少必填字段: {field_name}")
        elif not isinstance(data[field_name], field_type):
            errors.append(
                f"字段类型错误: {field_name} 应为 {field_type.__name__}，"
                f"实际为 {type(data[field_name]).__name__}"
            )

    # 如果必填字段缺失，后续校验无意义
    if errors:
        return errors

    # ID 格式
    article_id = data["id"]
    if not ID_PATTERN.match(article_id):
        errors.append(
            f"ID 格式错误: '{article_id}'，"
            f"应为 '{{source}}-{{YYYYMMDD}}-{{NNN}}'"
        )

    # 标题非空
    if not data["title"].strip():
        errors.append("标题不能为空")

    # URL 格式
    source_url = data["source_url"]
    if not URL_PATTERN.match(source_url):
        errors.append(f"URL 格式错误: '{source_url}'")

    # 摘要长度
    summary = data["summary"]
    if len(summary.strip()) < SUMMARY_MIN_LENGTH:
        errors.append(
            f"摘要太短: {len(summary.strip())} 字，"
            f"要求至少 {SUMMARY_MIN_LENGTH} 字"
        )

    # 标签非空
    tags = data["tags"]
    if len(tags) == 0:
        errors.append("至少需要 1 个标签")
    for tag in tags:
        if not isinstance(tag, str) or not tag.strip():
            errors.append(f"标签格式错误: '{tag}'")

    # status 值
    status = data["status"]
    if status not in VALID_STATUSES:
        errors.append(
            f"无效的 status: '{status}'，"
            f"允许值: {', '.join(sorted(VALID_STATUSES))}"
        )

    # score 范围（可选字段，存在时校验）
    if "score" in data:
        score = data["score"]
        if not isinstance(score, (int, float)):
            errors.append(f"score 应为数字，实际为 {type(score).__name__}")
        elif not (SCORE_MIN <= score <= SCORE_MAX):
            errors.append(
                f"score 超出范围: {score}，"
                f"允许范围: {SCORE_MIN}-{SCORE_MAX}"
            )

    # audience（可选字段，存在时校验）
    if "audience" in data:
        audience = data["audience"]
        if audience not in VALID_AUDIENCES:
            errors.append(
                f"无效的 audience: '{audience}'，"
                f"允许值: {', '.join(sorted(VALID_AUDIENCES))}"
            )

    return errors


# ── CLI 入口 ─────────────────────────────────────────────────────────────

def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python hooks/validate_json.py <json_file> [json_file2 ...]")
        print("示例: python hooks/validate_json.py knowledge/articles/*.json")
        return 1

    files = sys.argv[1:]
    total_files = 0
    failed_files = 0
    all_errors: dict[str, list[str]] = {}

    for filepath in files:
        path = Path(filepath)
        if not path.exists():
            print(f"[SKIP] 文件不存在: {filepath}")
            continue
        if not path.suffix == ".json":
            print(f"[SKIP] 非 JSON 文件: {filepath}")
            continue

        total_files += 1

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            all_errors[filepath] = [f"JSON 解析失败: {e}"]
            failed_files += 1
            continue

        errors = validate_article(data)
        if errors:
            all_errors[filepath] = errors
            failed_files += 1

    # 输出结果
    print(f"\n{'='*50}")
    print(f"JSON 格式校验结果")
    print(f"{'='*50}")

    if all_errors:
        for filepath, errors in all_errors.items():
            print(f"\n[FAIL] {filepath}")
            for err in errors:
                print(f"  - {err}")
    else:
        print("\n[PASS] 所有文件校验通过")

    print(f"\n总计: {total_files} 文件, {total_files - failed_files} 通过, {failed_files} 失败")

    return 1 if failed_files > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
