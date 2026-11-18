"""按日期 + 地域补抓历史新闻（命令行）。

示例（补 2026-10-05 广州的新闻）：
    .venv/bin/python scripts/backfill.py --date 2026-10-05 --city 广州市
    .venv/bin/python scripts/backfill.py --from 2026-10-01 --to 2026-10-07 --city 广州市
    .venv/bin/python scripts/backfill.py --date 2026-10-05 --province 山东省 --city 烟台市 --pages 60

补抓只扫命中的源，深翻历史列表页；命中日期的入库，不推进水位。
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.crawler.runner import run_backfill  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="按日期+地域补抓历史新闻")
    p.add_argument("--date", help="单日 YYYY-MM-DD（等价于 --from/--to 同一天）")
    p.add_argument("--from", dest="date_from", help="起始日期 YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", help="结束日期 YYYY-MM-DD")
    p.add_argument("--province", default="")
    p.add_argument("--city", default="")
    p.add_argument("--district", default="")
    p.add_argument("--area", default="")
    p.add_argument("--org", default="")
    p.add_argument("--level", default="")
    p.add_argument("--source-id", type=int)
    p.add_argument("--source-ids", default="", help="逗号分隔的源 ID，用于分批执行（只补这些源）")
    p.add_argument("--pages", type=int, default=40, help="每源最多翻多少页（1-80）")
    p.add_argument("--concurrency", type=int, default=0, help="并发源数（0=用配置默认 3，上限 8）")
    args = p.parse_args()

    single = datetime.strptime(args.date, "%Y-%m-%d") if args.date else None
    date_from = single or (datetime.strptime(args.date_from, "%Y-%m-%d")
                           if args.date_from else None)
    date_to = single or (datetime.strptime(args.date_to, "%Y-%m-%d")
                         if args.date_to else None)
    if not date_from and not date_to:
        p.error("请指定 --date 或 --from/--to")

    region = {"province": args.province, "city": args.city,
              "district": args.district, "area": args.area,
              "org": args.org, "level": args.level}

    source_ids = [int(x) for x in args.source_ids.split(",") if x.strip().isdigit()]

    async def job():
        return await run_backfill(
            date_from=date_from, date_to=date_to, region=region,
            source_id=args.source_id, source_ids=source_ids or None,
            max_pages=max(1, min(80, args.pages)),
            concurrency=args.concurrency if args.concurrency > 0 else None,
            progress_cb=lambda x: print(
                f"[{x['done']}/{x['total']}] {x['current']}", flush=True),
        )

    result = asyncio.run(job())
    if result.get("locked"):
        print(json.dumps({"locked": True, "message": result["message"]},
                         ensure_ascii=False, indent=2))
        return
    print(json.dumps({
        "sources": result["sources"],
        "inserted": result["inserted"],
        "errors": [r for r in result["results"]
                   if r["status"] != "ok" or r["inserted"]][:20],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
