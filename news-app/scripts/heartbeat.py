"""每日 09:00 独立存活心跳 + 周报 / 月报触发。

关键设计：这是一个**独立于 Web 服务进程**的脚本，由系统级 launchd 定时拉起。
如果只用应用内 APScheduler 做心跳，服务进程整个挂掉时也发不出告警，
恰恰漏掉最需要报警的那种故障。因此它只用标准库 + notifier，不 import app.main。

检查项：HTTP 服务、数据库可读、最近抓取轮次、最新报告、最新备份、
AI 解读积压、磁盘余量。异常推红色告警，正常推轻量绿色摘要。
周一 09:00 顺带生成并推送上一周周报；每月 1 日顺带上月月报。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app.notifier import push_notice  # noqa: E402
from app.publisher import latest_meta  # noqa: E402

DB = ROOT / "data" / "news.db"
REPORTS = ROOT / "data" / "reports"
BACKUPS = ROOT / "data" / "backups"
HOST = "http://127.0.0.1:8300/"
STALE_HOURS = 26  # 每天 12/21 两轮，最长间隔 15h；超过 26h 必然是漏跑

checks: list[tuple[str, bool, str]] = []


def add(name: str, ok: bool, detail: str):
    checks.append((name, ok, detail))


def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def check_http():
    try:
        with _opener().open(HOST, timeout=8) as r:
            ok = r.status == 200
            add("Web 服务", ok, f"HTTP {r.status}" + ("" if ok else "（期望 200）"))
    except Exception as ex:  # noqa: BLE001
        add("Web 服务", False, f"无法连接 127.0.0.1:8300：{str(ex)[:100]}")


def check_database() -> sqlite3.Connection | None:
    conn = None
    try:
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
        total = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        add("数据库", True, f"可读，{total} 篇")
    except Exception as ex:  # noqa: BLE001
        add("数据库", False, f"读取失败：{str(ex)[:100]}")
        conn = None
    return conn


def check_last_round(conn):
    if conn is None:
        add("最近抓取轮次", False, "数据库不可用，跳过")
        return
    try:
        row = conn.execute(
            "SELECT MAX(started_at), COUNT(DISTINCT substr(started_at,1,13)), "
            "SUM(CASE WHEN status!='ok' THEN 1 ELSE 0 END) "
            "FROM fetch_logs WHERE started_at >= ?",
            ((datetime.now() - timedelta(hours=STALE_HOURS)).strftime("%Y-%m-%d %H:%M:%S"),),
        ).fetchone()
        if not row or not row[0]:
            add("最近抓取轮次", False, f"近 {STALE_HOURS} 小时没有任何抓取记录")
            return
        last = datetime.fromisoformat(str(row[0]).replace("T", " ")[:19])
        hours = (datetime.now() - last).total_seconds() / 3600
        failed = row[2] or 0
        add("最近抓取轮次", True,
            f"{last:%m-%d %H:%M}（{hours:.0f} 小时前，窗口内 {row[1]} 轮，源级失败 {failed}）")
    except Exception as ex:  # noqa: BLE001
        add("最近抓取轮次", False, f"查询失败：{str(ex)[:100]}")


def check_ai_health(conn):
    if conn is None:
        return
    try:
        pending = conn.execute("SELECT COUNT(*) FROM news WHERE status!='interpreted'").fetchone()[0]
        err = conn.execute("SELECT COUNT(*) FROM news WHERE ai_error IS NOT NULL AND ai_error!=''").fetchone()[0]
        add("AI 解读积压", pending == 0 and err == 0,
            f"待解读 {pending}｜AI 错误 {err}" +
            ("（额度恢复后下一轮自动补解读）" if pending or err else ""))
    except Exception as ex:  # noqa: BLE001
        add("AI 解读积压", False, f"查询失败：{str(ex)[:100]}")


def _fresh(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "文件不存在"
    hours = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 3600
    return hours <= STALE_HOURS, f"{hours:.0f} 小时前更新"


def check_report():
    ok, detail = _fresh(REPORTS / "latest.html")
    meta = latest_meta()
    add("最新执行报告", ok, f"{detail}｜轮次 {meta.get('round', '未知')}")


def check_backup():
    try:
        files = sorted(BACKUPS.glob("news-*.db"), key=lambda p: p.stat().st_mtime)
        if not files:
            add("数据库热备", False, "没有任何备份文件")
            return
        ok, detail = _fresh(files[-1])
        add("数据库热备", ok, f"{files[-1].name}｜{detail}｜共 {len(files)} 份")
    except Exception as ex:  # noqa: BLE001
        add("数据库热备", False, f"检查失败：{str(ex)[:100]}")


def check_disk():
    try:
        free_gb = shutil.disk_usage(ROOT).free / (1024 ** 3)
        add("磁盘余量", free_gb >= 1, f"剩余 {free_gb:.1f} GB")
    except Exception as ex:  # noqa: BLE001
        add("磁盘余量", False, f"检查失败：{str(ex)[:100]}")


def run_period(period: str):
    script = ROOT / "scripts" / "period_report.py"
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--period", period, "--notify"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=300,
        )
        print(f"[周期报告 {period}] exit={proc.returncode} {(proc.stdout or proc.stderr).strip()[:300]}")
    except Exception as ex:  # noqa: BLE001
        print(f"[周期报告 {period}] 失败（非阻断）: {str(ex)[:200]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只检查并打印，不推送、不生成周期报告")
    ap.add_argument("--no-period", action="store_true", help="跳过周报/月报触发")
    args = ap.parse_args()

    conn = check_database()
    check_http()
    check_last_round(conn)
    check_ai_health(conn)
    check_report()
    check_backup()
    check_disk()
    if conn:
        conn.close()

    ok = all(c[1] for c in checks)
    body = "\n".join(f"- {'✓' if c[1] else '✗'} **{c[0]}**：{c[2]}" for c in checks)
    if ok:
        title = "09:00 存活检查 · 全部正常"
        md = "**系统运行正常**\n\n" + body + "\n\n每日 12:00 / 21:00 自动抓取，报告推送到本群。"
    else:
        bad = [c for c in checks if not c[1]]
        title = f"【注意】09:00 存活检查 · {len(bad)} 项异常"
        md = ("**需要处理**\n\n" + body +
              "\n\n**建议**：先看服务是否在运行 `lsof -nP -iTCP:8300 -sTCP:LISTEN`；"
              "launchd 会在崩溃后约 10 秒自动拉起，若仍异常再手动 "
              "`launchctl kickstart -k gui/$(id -u)/com.jt.gov-news`。"
              "抓取轮次缺失可等 12:00 那轮补跑。")

    print(f"{title}\n{md}")
    # launchd 与 WorkBuddy 自动化是双保险，可能在同一天先后触发；
    # 按「日期 + 状态」去重，状态由正常变异常时仍会再推一条告警。
    stamp = ROOT / "data" / "heartbeat.last"
    state = f"{datetime.now():%Y-%m-%d}:{'ok' if ok else 'error'}"
    pushed = False
    if not args.dry_run:
        prev = stamp.read_text(encoding="utf-8").strip() if stamp.exists() else ""
        if prev == state:
            print("今日同状态已推送，跳过（双调度去重）")
        else:
            res = push_notice(title, md, red=not ok)
            print("推送: " + json.dumps(res, ensure_ascii=False))
            stamp.write_text(state, encoding="utf-8")
            pushed = True

    now = datetime.now()
    if pushed and not args.no_period:
        if now.weekday() == 0:  # 周一
            run_period("weekly")
        if now.day == 1:
            run_period("monthly")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
