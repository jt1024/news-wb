"""跨进程互斥锁：保证同一时刻只有一个抓取轮次 / 一次自检在跑。

Web 服务内的 APScheduler、独立脚本 scripts/run_round.py 和 watchdog 可能
同时触发同一轮。用 flock 非阻塞锁，抢不到的一方直接跳过，避免重复抓取、
重复生成报告、重复推送飞书。锁由内核持有，进程异常退出也会自动释放。
"""
from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@contextmanager
def exclusive_lock(name: str):
    """yield True 表示拿到锁；False 表示已有其它进程持有（调用方应跳过）。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{name}.lock"
    with open(path, "a+", encoding="utf-8") as f:
        got = False
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            got = True
            f.seek(0)
            f.truncate()
            f.write(f"pid={os.getpid()}\n")
            f.flush()
        except (BlockingIOError, OSError):
            got = False
        try:
            yield got
        finally:
            if got:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass


def round_lock():
    """抓取轮次专用锁。"""
    return exclusive_lock("round")
