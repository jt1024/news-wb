"""独立于 Web 服务的定时兜底守护（watchdog）。

背景：抓取与执行报告原本只挂在 Web 服务进程内的 APScheduler 上。
服务没起来时，12:00 / 21:00 两轮静默消失，飞书一条消息都收不到——
恰恰在最需要告警的时候没有告警。09:00 心跳虽独立，但一天只跑一次。

做法：由独立 LaunchAgent 每 30 分钟拉起本脚本（或 --loop 常驻），
不 import app.main、不经过 8300 端口，只用标准库 + 只读 SQLite + notifier：

  1. 服务掉线  -> 红色告警，并尝试 launchctl kickstart / 拉起临时服务
  2. 整轮漏跑  -> 红色告警，并后台触发 run_round.py 独立补跑一轮
                  （补跑自己会生成报告并推送飞书，不依赖服务是否在线）
  3. 报告缺失  -> 红色告警，并补生成报告 + 推送
  4. 全部正常  -> 只写本地日志；若之前报过故障，补一条绿色「已恢复」

首次运行建立基线：不追溯上线前已漏掉的历史轮次。
告警按「故障类型 + 轮次」去重，同类故障默认 6 小时内只推一次。

用法：
    .venv/bin/python scripts/watchdog.py --dry-run     # 只检查不推送/不自愈
    .venv/bin/python scripts/watchdog.py               # 单次检查
    .venv/bin/python scripts/watchdog.py --loop        # 常驻，每 30 分钟自检
    .venv/bin/python scripts/watchdog.py --loop --no-pid-file
                                                       # launchd KeepAlive 托管用
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.notifier import push_notice  # noqa: E402  先让 .env 覆盖生效
from app import config  # noqa: E402
from app.publisher import latest_meta  # noqa: E402
from app.round_guard import exclusive_lock  # noqa: E402
from app.watchdog_logic import (  # noqa: E402
    alert_key, find_issues, latest_due_round, parse_ts,
    should_alert, should_retry_action,
)

DB = ROOT / "data" / "news.db"
STATE_FILE = ROOT / "data" / "watchdog.state.json"
PID_FILE = ROOT / "data" / "watchdog.pid"
LOG_FILE = ROOT / "data" / "watchdog.log"
ROUND_LOG = ROOT / "data" / "watchdog.round.log"
HOST = "http://127.0.0.1:8300/"


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


def env_flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "off", "no")


def log_line(text: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    print(line.rstrip(), flush=True)


def load_state() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def _opener():
    # 必须绕开环境里的 HTTP_PROXY：否则代理返回的 502 会被当成服务在线。
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def service_ok() -> bool:
    try:
        with _opener().open(HOST, timeout=5) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def wait_http(seconds: int) -> bool:
    for _ in range(seconds):
        if service_ok():
            return True
        time.sleep(1)
    return False


def last_fetch_at() -> datetime | None:
    try:
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute("SELECT MAX(started_at) FROM fetch_logs").fetchone()
        finally:
            conn.close()
        return parse_ts(row[0] if row else None)
    except Exception:  # noqa: BLE001
        return None


def report_at() -> datetime | None:
    return parse_ts(latest_meta().get("generated_at"))


def recover_service() -> str:
    """先让 launchd 重启服务；未注册时拉起临时 uvicorn 保证定时轮次能跑。"""
    label = f"gui/{os.getuid()}/com.jt.gov-news"
    try:
        subprocess.run(["launchctl", "kickstart", "-k", label],
                       capture_output=True, timeout=10, check=False)
        if wait_http(6):
            return "launchd kickstart 已拉起服务，定时任务恢复"
    except Exception:  # noqa: BLE001
        pass

    try:
        with open(ROOT / "data" / "server.out.log", "ab") as out:
            out.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} watchdog 拉起临时服务 ===\n".encode())
            out.flush()
            subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app",
                 "--host", "127.0.0.1", "--port", "8300"],
                cwd=str(ROOT), stdout=out, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        if wait_http(15):
            return ("已拉起临时服务（临时进程不保证跨会话存活，"
                    "建议双击 run_launchd_install.command 交回 launchd）")
    except Exception as ex:  # noqa: BLE001
        return f"自动拉起异常：{str(ex)[:120]}"
    return "自动拉起未成功，需人工检查 8300 端口与服务日志"


def trigger_round() -> str:
    """后台启动独立补跑；它自己会生成报告并推送飞书，watchdog 不等它。"""
    try:
        with open(ROUND_LOG, "ab") as out:
            out.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} watchdog 触发独立补跑 ===\n".encode())
            out.flush()
            proc = subprocess.Popen(
                [sys.executable, str(ROOT / "scripts" / "run_round.py")],
                cwd=str(ROOT), stdout=out, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return f"已后台启动独立补跑（PID {proc.pid}），完成后自动推送本轮执行报告"
    except Exception as ex:  # noqa: BLE001
        return f"补跑启动失败：{str(ex)[:120]}"


def trigger_report() -> str:
    """抓取已跑但报告没生成/没推送：补生成并推送最近一轮。"""
    try:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "execution_report.py"), "--notify"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=180, check=False,
        )
        tail = (proc.stdout or proc.stderr or "").strip()[-200:]
        return f"补发报告 exit={proc.returncode}｜{tail}" if tail else f"补发报告 exit={proc.returncode}"
    except Exception as ex:  # noqa: BLE001
        return f"补发报告失败：{str(ex)[:120]}"


def check_once(*, dry_run: bool = False, auto_recover: bool = True,
               auto_run: bool = True) -> int:
    with exclusive_lock("watchdog") as got:
        if not got:
            print("已有 watchdog 实例在执行，本次跳过", flush=True)
            return 0
        return _check_once(dry_run=dry_run, auto_recover=auto_recover,
                           auto_run=auto_run)


def _check_once(*, dry_run: bool, auto_recover: bool, auto_run: bool) -> int:
    now = datetime.now()
    state = load_state()
    first_run = not state.get("baseline_at")
    if first_run:
        baseline = now
        state["baseline_at"] = baseline.isoformat(timespec="seconds")
    else:
        baseline = parse_ts(state.get("baseline_at")) or now

    grace = env_int("WATCHDOG_GRACE_MIN", 30)
    cooldown = env_int("WATCHDOG_ALERT_COOLDOWN_HOURS", 6)
    retry_min = env_int("WATCHDOG_RETRY_MIN", 60)
    due = latest_due_round(now, config.CRON_HOURS, config.CRON_MINUTE, grace)
    ok_http = service_ok()
    lf = last_fetch_at()
    ra = report_at()
    issues = find_issues(service_ok=ok_http, last_fetch=lf, report_at=ra,
                         due=due, baseline_at=baseline)

    due_text = f"{due:%m-%d %H:%M}" if due else "无（尚未到宽限期）"
    details = [
        f"- {'✓' if ok_http else '✗'} **Web 服务**：{'HTTP 200' if ok_http else '8300 无响应'}",
        f"- **应完成轮次**：{due_text}（宽限 {grace} 分钟）",
        f"- **最近抓取**：{lf:%m-%d %H:%M}" if lf else "- **最近抓取**：无记录",
        f"- **最近报告**：{ra:%m-%d %H:%M}" if ra else "- **最近报告**：无记录",
    ]
    if first_run:
        details.append("- 本次为守护首次运行，已建立基线，上线前的历史轮次不追溯")

    if not issues:
        if state.get("last_issue") and not dry_run:
            res = push_notice(
                "兜底守护 · 系统已恢复",
                "**之前报告的异常已消除，12:00 / 21:00 抓取与推送恢复正常。**\n\n"
                + "\n".join(details), red=False,
            )
            log_line(f"恢复通知推送: {json.dumps(res, ensure_ascii=False)[:160]}")
            state["alerts"] = {}
        state["last_issue"] = False
        save_state(state)
        log_line("检查正常（不推送，避免噪音）")
        return 0

    names = {"service": "Web 服务掉线", "round": "定时轮次未执行",
             "report": "本轮报告未生成/未推送"}
    actions: list[str] = []
    if not dry_run:
        if "service" in issues and auto_recover:
            actions.append(f"- **服务自愈**：{recover_service()}")
        due_key = due.strftime("%Y-%m-%d %H") if due else "none"
        if "round" in issues and auto_run and due and should_retry_action(state, due_key, now, retry_min):
            actions.append(f"- **自动补跑**：{trigger_round()}")
            state.setdefault("handling", {})[due_key] = now.isoformat(timespec="seconds")
        elif "round" in issues and auto_run:
            actions.append(f"- **自动补跑**：已触发过，{retry_min} 分钟内不重复启动，等待本轮结果")
        if "report" in issues and auto_run:
            actions.append(f"- **补发报告**：{trigger_report()}")

    key = alert_key(issues, due)
    title = f"【兜底告警】{' / '.join(names[i] for i in issues)}"
    md = ("**定时任务没有按预期产出，已由独立守护介入**\n\n"
          + "\n".join(details)
          + "\n\n**自动处置**\n\n" + ("\n".join(actions) if actions else "- 本次为自检/已关闭自动处置")
          + f"\n\n**建议**：在 Finder 双击 `scripts/run_launchd_install.command` 让 launchd 接管服务，"
            "再双击 `scripts/run_watchdog_install.command` 让本守护也长期托管；"
            f"同类故障 {cooldown} 小时内只推一次，恢复后会另发一条绿色通知。")
    print(f"{title}\n{md}", flush=True)

    if not dry_run:
        if should_alert(state, key, now, cooldown):
            res = push_notice(title, md, red=True)
            log_line(f"告警推送: {json.dumps(res, ensure_ascii=False)[:200]}")
            if res.get("ok") is True:
                state.setdefault("alerts", {})[key] = now.isoformat(timespec="seconds")
            else:
                log_line("推送未成功，不标记冷却，下轮继续重试")
        else:
            log_line(f"同类告警冷却中，跳过推送：{key}")
        state["last_issue"] = True
    save_state(state)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只检查，不推送/不自愈/不补跑")
    ap.add_argument("--loop", action="store_true", help="常驻循环自检")
    ap.add_argument("--no-pid-file", action="store_true",
                    help="launchd KeepAlive 托管时不写 pid 文件，避免与安装脚本兜底进程混淆")
    ap.add_argument("--interval", type=int, default=env_int("WATCHDOG_INTERVAL", 1800),
                    help="loop 模式的自检间隔秒数")
    ap.add_argument("--no-recover", action="store_true", help="不自动拉起服务")
    ap.add_argument("--no-auto-run", action="store_true", help="不自动补跑/补发报告")
    args = ap.parse_args()

    auto_recover = env_flag("WATCHDOG_AUTO_RECOVER") and not args.no_recover
    auto_run = env_flag("WATCHDOG_AUTO_RUN") and not args.no_auto_run

    if not args.loop:
        return check_once(dry_run=args.dry_run, auto_recover=auto_recover,
                          auto_run=auto_run)

    if not args.no_pid_file:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
        atexit.register(lambda: PID_FILE.unlink(missing_ok=True))
    log_line(f"常驻守护启动 PID={os.getpid()} interval={args.interval}s")
    while True:
        try:
            check_once(auto_recover=auto_recover, auto_run=auto_run)
        except Exception as ex:  # noqa: BLE001  守护自身绝不能因单次异常退出
            log_line(f"自检异常（已忽略，下轮继续）：{str(ex)[:200]}")
        time.sleep(max(60, args.interval))
    return 0


if __name__ == "__main__":
    sys.exit(main())
