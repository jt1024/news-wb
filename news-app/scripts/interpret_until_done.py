"""解读守护：按恢复时间表消化所有待解读新闻，402 中断后自动等下一个窗口续跑。

用法：.venv/bin/python scripts/interpret_until_done.py <恢复时间1> [恢复时间2 ...]
  例：额度 00:01 和 05:01 恢复 → scripts/interpret_until_done.py 00:01 05:01

流程：等到最近的恢复时间 → 探活 → 启动 5 个分片 worker → 等全部退出 →
若仍剩待解读且因 402 中止，则等到下一个恢复时间续跑；时间表用尽或跑完即退出并打印汇总。
"""
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

DB = os.path.join(ROOT, "data", "news.db")
WORKERS = 5
BATCH = 20


def pending() -> int:
    c = sqlite3.connect(DB)
    n = c.execute("select count(*) from news where status='fetched'").fetchone()[0]
    c.close()
    return n


def quota_ok() -> bool:
    from app.ai.client import chat, AIQuotaError
    try:
        chat([{"role": "user", "content": "回复OK"}], max_tokens=2000)
        return True
    except AIQuotaError:
        return False


def next_slot(times, after: datetime):
    """times: ['HH:MM', ...]，返回 after 之后最近的恢复时刻。"""
    cands = []
    for t in times:
        h, m = map(int, t.split(":"))
        for day in (0, 1):
            cand = after.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=day)
            if cand > after:
                cands.append(cand)
                break
    return min(cands) if cands else None


def run_wave(tag: str) -> bool:
    """启动 5 个 worker 并等待结束。返回是否因 402 中止（查日志 ABORT 行）。"""
    procs = []
    for k in range(WORKERS):
        log = open(os.path.join(ROOT, "data", f"interpret_w{k}.log"), "a")
        p = subprocess.Popen(
            [sys.executable, "-u", os.path.join(ROOT, "scripts", "interpret_worker.py"),
             str(WORKERS), str(k), str(BATCH)],
            stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
        procs.append(p)
    exits = [p.wait() for p in procs]
    aborted_402 = False
    crashed = []
    for k, rc in enumerate(exits):
        with open(os.path.join(ROOT, "data", f"interpret_w{k}.log"), "rb") as f:
            tail = f.read()[-2000:].decode("utf-8", "ignore")
        if "ABORT" in tail and "402" in tail:
            aborted_402 = True
        elif rc != 0:
            # worker 异常退出（如 news_tags 唯一约束冲突），不能当成"正常完成"，
            # 否则剩余条目会被留在库里永远没人处理。
            crashed.append((k, rc))
    state = "402中止" if aborted_402 else ("异常退出" if crashed else "正常完成")
    if crashed:
        print(f"[watcher] {tag} worker 异常退出: {crashed}", flush=True)
    print(f"[watcher] {tag} 本轮结束 {state} 剩余={pending()}", flush=True)
    # 有崩溃或 402 都返回 True（需续跑）；只有全部 worker 干净退出才返回 False
    return aborted_402 or bool(crashed)


def main():
    times = sys.argv[1:] or ["00:01"]
    print(f"[watcher] START {datetime.now():%m-%d %H:%M:%S} 待解读={pending()} "
          f"恢复时间表={times}", flush=True)
    while pending() > 0:
        slot = next_slot(times, datetime.now())
        if slot is None:
            print(f"[watcher] STOP 时间表用尽仍有剩余={pending()}，等下次人工恢复", flush=True)
            break
        wait_s = (slot - datetime.now()).total_seconds()
        if wait_s > 0:
            print(f"[watcher] 等待额度窗口 {slot:%m-%d %H:%M}（{wait_s/60:.0f} 分钟）", flush=True)
            time.sleep(wait_s)
        if not quota_ok():
            print(f"[watcher] {datetime.now():%H:%M} 探活仍 402，跳过本窗口", flush=True)
            continue
        print(f"[watcher] {datetime.now():%H:%M} 探活通过，启动 worker", flush=True)
        aborted = run_wave(slot.strftime("%H:%M"))
        if pending() == 0:
            break
        if not aborted:
            print(f"[watcher] STOP 非 402 原因停止，剩余={pending()}，需人工检查", flush=True)
            break
        # 402 中止：继续循环等下一个窗口
    p = pending()
    print(f"[watcher] DONE {datetime.now():%m-%d %H:%M:%S} | "
          f"{'全部解读完成' if p == 0 else f'剩余 {p} 篇未解读'}", flush=True)


if __name__ == "__main__":
    main()
