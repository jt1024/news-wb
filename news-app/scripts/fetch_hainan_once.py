"""只抓取海南省 26 个新源一次（2026-11-19 接入首抓）。

复用 runner.run_fetch(source_id=...) 的单源抓取逻辑，不跑解读/热备/推送，
不影响同时进行的解读 backlog 任务。结果写入 data/hainan_first_fetch.json。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.crawler.runner import run_fetch  # noqa: E402


async def main():
    con = sqlite3.connect(ROOT / "data" / "news.db")
    rows = con.execute(
        "select id,name from sources where region_province='海南省' and level in ('city','district') order by id"
    ).fetchall()
    con.close()
    print(f"海南新源 {len(rows)} 个，开始首抓", flush=True)
    results = []
    for i, (sid, name) in enumerate(rows, 1):
        try:
            r = await run_fetch(source_id=sid, page_max=6)
            res = r["results"][0] if r["results"] else {"status": "none", "inserted": 0}
            results.append({"id": sid, "name": name, **res})
            print(f"[{i:>2}/{len(rows)}] {name[:22]:<22} "
                  f"{res.get('status')} 入库 {res.get('inserted', 0)}", flush=True)
        except Exception as e:
            results.append({"id": sid, "name": name, "status": "error",
                            "error": f"{type(e).__name__}: {str(e)[:80]}"})
            print(f"[{i:>2}/{len(rows)}] {name[:22]:<22} ERROR {e}", flush=True)
    out = ROOT / "data" / "hainan_first_fetch.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(x.get("inserted", 0) or 0 for x in results)
    ok = sum(1 for x in results if x.get("status") == "ok")
    print(f"\n完成: {ok}/{len(results)} 源 ok，共入库 {total} 篇 -> {out}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
