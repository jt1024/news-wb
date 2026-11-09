"""独立跑完整一轮：抓取 → 解读 → 热备 → 生成报告并推送。

不启动 Web 服务、不经过 8300 端口、不依赖 APScheduler。watchdog 发现
12:00 / 21:00 的轮次漏跑时调用本脚本，因此「服务没起来」也不会静默。
与服务内调度共用 data/round.lock，谁先抢到锁谁执行，另一方直接跳过。

用法：.venv/bin/python scripts/run_round.py [--timeout 1800]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.round_guard import round_lock  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=1800,
                    help="整轮最长执行秒数，防止 AI/网络卡死占住锁")
    args = ap.parse_args()

    with round_lock() as got:
        if not got:
            print("已有抓取轮次在执行，本次跳过（避免重复抓取和重复推送）")
            return 0
        from app.scheduler import _run_pipeline

        print("独立补跑开始", flush=True)
        asyncio.run(asyncio.wait_for(_run_pipeline(), timeout=args.timeout))
        print("独立补跑完成", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
