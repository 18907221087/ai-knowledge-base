"""
pipeline/rss_reader.py — RSS 数据源采集模块

支持从任意 RSS 源采集内容，配置文件见 pipeline/rss_sources.yaml。

用法:
    # 作为模块被 pipeline.py 导入
    from pipeline.rss_reader import collect_rss
    items = collect_rss(limit=10)

    # 独立运行（调试）
    python3 -m pipeline.rss_reader
    python3 -m pipeline.rss_reader --limit 5
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

logger = logging.getLogger(__name__)

# RSS 配置文件与 pipeline.py 共享同一份
RSS_CONFIG = Path(__file__).parent / "rss_sources.yaml"


def collect_rss(limit: int = 10) -> list[dict[str, Any]]:
    """
    从配置的 RSS 源采集内容。

    Args:
        limit: 最大采集数量（所有源合计）

    Returns:
        原始数据列表，每条包含 id/title/source/source_url/... 字段
    """
    if not RSS_CONFIG.exists():
        logger.warning("RSS 配置文件不存在: %s", RSS_CONFIG)
        return []

    with open(RSS_CONFIG, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    sources = [s for s in config.get("sources", []) if s.get("enabled", True)]
    results: list[dict[str, Any]] = []
    count = 0

    with httpx.Client(timeout=20.0) as client:
        for source in sources:
            if count >= limit:
                break

            try:
                resp = client.get(source["url"])
                resp.raise_for_status()
                feed_text = resp.text

                # 简易 RSS 解析：提取 <item> 中的 <title> 和 <link>
                items = re.findall(
                    r"<item[^>]*>.*?<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>.*?"
                    r"<link[^>]*>(.*?)</link>.*?</item>",
                    feed_text,
                    re.DOTALL,
                )

                for title, link in items:
                    if count >= limit:
                        break
                    title = title.strip()
                    link = link.strip()
                    if not title or not link:
                        continue

                    now = datetime.now(timezone.utc).isoformat()
                    count += 1
                    results.append({
                        "id": f"rss-{datetime.now().strftime('%Y%m%d')}-{count:03d}",
                        "title": title,
                        "source": f"rss:{source['name']}",
                        "source_url": link,
                        "author": source.get("name", "unknown"),
                        "published_at": now,
                        "raw_description": "",
                        "category": source.get("category", "general"),
                        "collected_at": now,
                    })

                logger.info("RSS [%s] 采集: %d 条", source["name"], len(items))

            except httpx.HTTPError as e:
                logger.warning("RSS 源 [%s] 获取失败: %s", source["name"], e)

    logger.info("RSS 采集完成: 共 %d 条", len(results))
    return results


# ── 独立调试入口 ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="RSS 数据源采集调试入口")
    parser.add_argument("--limit", type=int, default=10, help="最大采集条数")
    parser.add_argument("--output", type=str, default="", help="保存到 JSON 文件（可选）")
    args = parser.parse_args()

    items = collect_rss(limit=args.limit)
    print(f"\n采集到 {len(items)} 条 RSS 条目")
    for i, item in enumerate(items[:5], 1):
        print(f"  {i}. [{item['source']}] {item['title'][:60]}")
    if len(items) > 5:
        print(f"  ... 还有 {len(items) - 5} 条")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        print(f"\n已保存到: {args.output}")
