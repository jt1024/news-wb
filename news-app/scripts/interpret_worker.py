"""并行解读 worker：按 news.id % N == k 分片消化待解读新闻。

多个 worker 同时运行时各管一个互不重叠的 id 分片，不会重复调 AI；
配合 SQLite WAL 模式与短事务提交，可安全并发写库。

用法：.venv/bin/python scripts/interpret_worker.py <分片总数N> <本片序号k> [每批条数]
  例：5 个 worker 并行 → 分别以 N=5, k=0..4 启动。

遇 402 额度不足立即退出；分片内无待解读即退出。
"""
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from sqlalchemy import select  # noqa: E402

from app import config  # noqa: E402
from app.ai.client import AIQuotaError  # noqa: E402
from app.ai.pipeline import interpret_one, interpret_rough_batch, is_rough  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import News  # noqa: E402

DB = os.path.join(ROOT, "data", "news.db")

MOD_N = int(sys.argv[1]) if len(sys.argv) > 1 else 1
MOD_K = int(sys.argv[2]) if len(sys.argv) > 2 else 0
BATCH = int(sys.argv[3]) if len(sys.argv) > 3 else 20

TAG = f"[w{MOD_K}/{MOD_N}]"


def pending_count() -> int:
    c = sqlite3.connect(DB)
    n = c.execute("select count(*) from news where status='fetched' and id % ? = ?",
                  (MOD_N, MOD_K)).fetchone()[0]
    c.close()
    return n


def main():
    print(f"{TAG} START {time.strftime('%H:%M:%S')} 本片待解读={pending_count()} 每批={BATCH}", flush=True)
    ok = failed = 0
    t0 = time.time()
    db = SessionLocal()
    try:
        while True:
            rows = db.execute(
                select(News)
                .where(News.status == "fetched", News.id % MOD_N == MOD_K)
                .order_by(News.id)
                .limit(BATCH)
            ).scalars().all()
            if not rows:
                break
            # 两档路由：分界日前的旧闻打包粗略解读，其余逐篇细致解读
            rough = [n for n in rows if is_rough(n)]
            detail = [n for n in rows if not is_rough(n)]
            chunk_size = max(1, config.ROUGH_INTERPRET_BATCH)
            try:
                for i in range(0, len(rough), chunk_size):
                    chunk = rough[i:i + chunk_size]
                    c_ok, c_fail = interpret_rough_batch(db, chunk)
                    ok += c_ok
                    failed += c_fail
                    db.commit()
                for news in detail:
                    if interpret_one(db, news):
                        ok += 1
                    else:
                        failed += 1
                    db.commit()
            except AIQuotaError as e:
                db.commit()
                print(f"{TAG} ABORT {time.strftime('%H:%M:%S')} 额度不足：{e}", flush=True)
                return
            print(f"{TAG} {time.strftime('%H:%M:%S')} 本批 {len(rows)}"
                  f"（粗略{len(rough)}/细致{len(detail)}）| "
                  f"累计 ok={ok} fail={failed} | 本片剩余={pending_count()} | "
                  f"耗时 {time.time()-t0:.0f}s", flush=True)
    finally:
        db.close()
    print(f"{TAG} DONE {time.strftime('%H:%M:%S')} 耗时 {time.time()-t0:.0f}s | "
          f"成功={ok} 失败={failed} 本片剩余={pending_count()}", flush=True)


if __name__ == "__main__":
    main()
