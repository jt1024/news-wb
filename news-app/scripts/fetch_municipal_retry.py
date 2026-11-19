"""补抓首抓入库 0 篇的 18 个直辖市区县源（低并发 + 长超时）。"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.crawler.runner import run_fetch  # noqa: E402

CONCURRENCY = 3
TIMEOUT = 200


async def fetch_one(sid, name, sem, slot):
    async with sem:
        try:
            r = await asyncio.wait_for(run_fetch(source_id=sid, page_max=2), timeout=TIMEOUT)
            res = r["results"][0] if r["results"] else {"status": "none", "inserted": 0}
            out = {"id": sid, "name": name, **res}
        except asyncio.TimeoutError:
            out = {"id": sid, "name": name, "status": "timeout", "inserted": 0}
        except Exception as e:
            out = {"id": sid, "name": name, "status": "error",
                   "inserted": 0, "error": f"{type(e).__name__}: {str(e)[:80]}"}
        print(f"[{slot:>2}] {name[:24]:<24} "
              f"{str(out.get('status')):<9} 入库 {out.get('inserted', 0)}", flush=True)
        return out


async def main():
    first = json.loads((ROOT / "data" / "municipal_first_fetch.json").read_text())
    zero = [x for x in first if (x.get("inserted") or 0) == 0]
    print(f"补抓 {len(zero)} 个零入库源，并发 {CONCURRENCY}，超时 {TIMEOUT}s", flush=True)
    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [fetch_one(x["id"], x["name"], sem, i) for i, x in enumerate(zero, 1)]
    results = await asyncio.gather(*tasks)
    total = sum(x.get("inserted", 0) or 0 for x in results)
    out = ROOT / "data" / "municipal_retry_fetch.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n补抓完成: 共入库 {total} 篇", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
