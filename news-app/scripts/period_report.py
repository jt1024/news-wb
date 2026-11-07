"""周期报告 CLI：生成上一完整周 / 月的统计报告，可选推送飞书。

用法：
  .venv/bin/python scripts/period_report.py --period weekly --notify
  .venv/bin/python scripts/period_report.py --period monthly --date 2026-12-01
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app.notifier import push_notice  # noqa: E402
from app.period_report import generate, summary_markdown  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", choices=["weekly", "monthly"], default="weekly")
    ap.add_argument("--date", help="以该日作为今天计算上一完整周期，格式 YYYY-MM-DD")
    ap.add_argument("--notify", action="store_true", help="生成后推送飞书")
    args = ap.parse_args()

    today = date.fromisoformat(args.date) if args.date else None
    d = generate(args.period, today)
    name = "周报" if args.period == "weekly" else "月报"
    print(f"已生成 {name}: {d['label']}｜发布 {d['total']} 篇｜日均 {d['daily_avg']}｜AI 综述 {'有' if d['summary'] else '降级'}")
    print("  " + d["html_path"])
    print("  " + d["md_path"])
    if args.notify:
        res = push_notice(f"广东政务新闻{name} · {d['label']}", summary_markdown(d))
        print("  推送: " + json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
