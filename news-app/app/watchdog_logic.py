"""兜底守护的纯判定逻辑：无 I/O、无副作用，便于单测。

服务挂掉时最需要告警，但抓取与报告原本都挂在服务进程内的调度上，
服务没起来就一条消息都发不出。watchdog 独立运行，只靠下面这些判断
决定「要不要报警 / 要不要补跑」。
"""
from __future__ import annotations

from datetime import datetime, timedelta


def parse_ts(value) -> datetime | None:
    """兼容 2026-11-08T21:04:15 / 2026-11-08 21:04:15 / 带微秒。"""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", ""))
    except (ValueError, TypeError):
        return None


def latest_due_round(now: datetime, hours: list[int], minute: int = 0,
                     grace_minutes: int = 30) -> datetime | None:
    """返回最近一个「应已完成」的定时轮次时刻（过了宽限期才算应完成）。

    只看今天与前两天，跨天时（例如凌晨检查昨晚 21:00 那轮）也能覆盖。
    """
    cutoff = now - timedelta(minutes=grace_minutes)
    candidates: list[datetime] = []
    for days_ago in (0, 1, 2):
        day = (now - timedelta(days=days_ago)).date()
        for h in hours:
            candidates.append(datetime(day.year, day.month, day.day, h, minute))
    past = [c for c in candidates if c <= cutoff]
    return max(past) if past else None


def find_issues(*, service_ok: bool, last_fetch: datetime | None,
                report_at: datetime | None, due: datetime | None,
                baseline_at: datetime | None = None) -> list[str]:
    """返回问题代码：service（服务掉线）/ round（整轮漏跑）/ report（报告缺失）。

    baseline_at 是守护上线的时刻：上线之前已漏掉的历史轮次不追溯，
    避免守护刚装好就翻旧账、重复补跑历史轮次。
    """
    issues: list[str] = []
    if not service_ok:
        issues.append("service")
    if due is None:
        return issues
    if baseline_at is not None and due < baseline_at:
        return issues
    if last_fetch is None or last_fetch < due:
        issues.append("round")
    elif report_at is None or report_at < due:
        issues.append("report")
    return issues


def alert_key(issues: list[str], due: datetime | None) -> str:
    """同一类故障 + 同一轮次合并成一条告警，避免每 30 分钟刷屏。

    纯「服务掉线」按类型固定去重：否则轮次从 12 点翻到 21 点时 key 变了，
    冷却会被绕过，长时间故障反而变成每轮推一条。
    """
    kinds = sorted(issues)
    if kinds == ["service"]:
        return "service"
    stamp = due.strftime("%Y-%m-%d %H") if due else "none"
    return f"{stamp}:{'+'.join(kinds)}"


def should_alert(state: dict, key: str, now: datetime,
                 cooldown_hours: float = 6) -> bool:
    prev = parse_ts((state.get("alerts") or {}).get(key))
    if prev is None:
        return True
    return (now - prev).total_seconds() >= cooldown_hours * 3600


def should_retry_action(state: dict, due_key: str, now: datetime,
                        retry_minutes: int = 60) -> bool:
    """同一轮次的自动补跑最多每 retry_minutes 分钟触发一次。"""
    prev = parse_ts((state.get("handling") or {}).get(due_key))
    if prev is None:
        return True
    return (now - prev).total_seconds() >= retry_minutes * 60
