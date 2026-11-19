"""并发首抓四直辖市 70 个新源（2026-11-20 接入首抓）。

复用 runner.run_fetch(source_id=...) 的单源抓取逻辑；用 asyncio 并发 +
每源独立超时（90s），避免单个源的 WAF 求解/超时拖垮整体。不跑解读/热备/推送。
结果写入 data/municipal_first_fetch.json（保留首轮已抓的源结果）。
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

CONCURRENCY = 6
TIMEOUT = 120


async def fetch_one(sid: int, name: str, semaphore: asyncio.Semaphore, slot: int) -> dict:
    async with semaphore:
        try:
            r = await asyncio.wait_for(
                run_fetch(source_id=sid, page_max=3), timeout=TIMEOUT)
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
    con = sqlite3.connect(ROOT / "data" / "news.db")
    rows = con.execute(
        "select id,name from sources where region_province in ('北京市','上海市','天津市','重庆市') "
        "and level='district' order by id"
    ).fetchall()
    con.close()
    # 保留首轮串行已抓成功的前 3 源结果（避免重复抓）
    prior = {}
    pf = ROOT / "data" / "municipal_first_fetch_round1.json"
    if pf.exists():
        for x in json.loads(pf.read_text()):
            prior[x["name"]] = x
    todo = [(sid, name) for sid, name in rows if name not in prior]
    print(f"直辖市区县源 {len(rows)} 个，已抓 {len(prior)}，待抓 {len(todo)}，"
          f"并发 {CONCURRENCY}，单源超时 {TIMEOUT}s", flush=True)
    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [fetch_one(sid, name, sem, i) for i, (sid, name) in enumerate(todo, 1)]
    results = list(prior.values()) + await asyncio.gather(*tasks)
    results.sort(key=lambda x: x["id"])
    out = ROOT / "data" / "municipal_first_fetch.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(x.get("inserted", 0) or 0 for x in results)
    ok = sum(1 for x in results if x.get("status") == "ok")
    print(f"\n完成: {ok}/{len(results)} 源 ok，共入库 {total} 篇 -> {out}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
