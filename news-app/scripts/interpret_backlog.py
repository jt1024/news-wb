"""消化所有待解读新闻（status=fetched），带节流与额度保护。

用法：.venv/bin/python scripts/interpret_backlog.py [每批条数]
  - 每批之间短暂休眠，避免触发 MiniMax 429
  - 遇 402 额度不足立即中止整轮，不浪费请求、不批量写失败标记
  - 可用于 API 额度恢复后的补跑，或定时任务之外的手动消化
"""
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from app.ai.client import AIQuotaError  # noqa: E402
from app.ai.pipeline import run_interpret  # noqa: E402

DB = os.path.join(ROOT, "data", "news.db")
BATCH = int(sys.argv[1]) if len(sys.argv) > 1 else 10
PAUSE = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
MAX_ROUNDS = 200


def stats():
    c = sqlite3.connect(DB)
    q = lambda s: c.execute(s).fetchone()[0]
    r = {
        "total": q("select count(*) from news"),
        # 港澳台地区稿件 status='skipped' 属预期（默认不解读），不计入待解读积压
        "pending": q("select count(*) from news where status!='interpreted' and level!='area'"),
        "done": q("select count(*) from news where status='interpreted'"),
        "errors": q("select count(*) from news where ai_error is not null and ai_error!=''"),
    }
    c.close()
    return r


def main():
    s = stats()
    print(f"START {time.strftime('%H:%M:%S')} 总量={s['total']} 待解读={s['pending']} 已解读={s['done']} 每批={BATCH}", flush=True)
    total_ok = total_failed = 0
    t0 = time.time()

    for round_no in range(1, MAX_ROUNDS + 1):
        try:
            res = run_interpret(BATCH)
        except AIQuotaError as e:
            print(f"ABORT {time.strftime('%H:%M:%S')} 额度不足，立即中止：{e}", flush=True)
            break
        total_ok += res["ok"]
        total_failed += res["failed"]
        s = stats()
        print(f"round {round_no:>3} {time.strftime('%H:%M:%S')} "
              f"本批 ok={res['ok']} fail={res['failed']} | "
              f"累计 ok={total_ok} fail={total_failed} | 剩余待解读={s['pending']}", flush=True)
        if res["processed"] == 0 or s["pending"] == 0:
            break
        time.sleep(PAUSE)

    s = stats()
    print(f"DONE {time.strftime('%H:%M:%S')} 耗时 {time.time()-t0:.0f}s | "
          f"累计成功={total_ok} 失败={total_failed} | "
          f"总量={s['total']} 已解读={s['done']} 待解读={s['pending']} 残留错误={s['errors']}", flush=True)


if __name__ == "__main__":
    main()
