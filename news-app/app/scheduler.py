"""定时任务：每日自动抓取 + 解读；支持手动触发（去重由抓取器保证）。

任务带实时进度上报：progress = {done, total, current, phase}
"""
import asyncio
import logging
import uuid
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import config

log = logging.getLogger("scheduler")
scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

# task_id -> {name, status, started_at, finished_at, result, progress}
_tasks: dict[str, dict] = {}


def _task_state() -> dict:
    return {k: {"name": v["name"], "status": v["status"],
                "started_at": v["started_at"], "finished_at": v["finished_at"],
                "result": v.get("result"), "progress": v.get("progress")}
            for k, v in list(_tasks.items())[-10:]}


def _set_progress(task_id: str, p: dict):
    if task_id in _tasks:
        _tasks[task_id]["progress"] = p


def _start_task(name: str, coro_factory, with_progress: bool = False) -> str:
    task_id = uuid.uuid4().hex[:8]
    _tasks[task_id] = {"name": name, "status": "running",
                       "started_at": datetime.now().isoformat(timespec="seconds"),
                       "finished_at": None, "result": None, "progress": None}

    async def _run():
        try:
            if with_progress:
                result = await coro_factory(lambda p: _set_progress(task_id, p))
            else:
                result = await coro_factory()
            _tasks[task_id]["result"] = result
            _tasks[task_id]["status"] = "ok"
        except Exception as e:  # noqa: BLE001
            log.exception("task %s failed", name)
            _tasks[task_id]["result"] = str(e)
            _tasks[task_id]["status"] = "error"
        _tasks[task_id]["finished_at"] = datetime.now().isoformat(timespec="seconds")

    asyncio.get_running_loop().create_task(_run())
    return task_id


def trigger_fetch(max_items: int = 50) -> str:
    from .crawler.runner import run_fetch

    def factory(cb):
        return run_fetch(max_items=max_items, progress_cb=cb)

    return _start_task("fetch", factory, with_progress=True)


def trigger_interpret(batch_size: int = 0) -> str:
    """循环消化全部积压：每批 batch_size（0=用配置默认），直到没有待解读。"""
    from .ai.pipeline import run_interpret

    async def job(cb):
        total = {"processed": 0, "ok": 0, "failed": 0, "rounds": 0}
        while total["rounds"] < 100:
            r = await asyncio.to_thread(run_interpret, batch_size, cb)
            total["processed"] += r["processed"]
            total["ok"] += r["ok"]
            total["failed"] += r["failed"]
            total["rounds"] += 1
            if r["processed"] == 0:
                break
        return total

    return _start_task("interpret", job, with_progress=True)


def trigger_report() -> str:
    """手动生成最近一轮的执行报告并推送（后台「立即生成」按钮 / 调试用）。"""
    async def job():
        return await generate_report_and_notify()

    return _start_task("report", job)


def _generate_report_sync() -> dict:
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "execution_report.py"), "--notify"],
        cwd=str(root), capture_output=True, text=True, timeout=180,
    )
    out, err = (proc.stdout or "").strip(), (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"exit {proc.returncode}: {(err or out)[:300]}")
    return {"output": out}


async def generate_report_and_notify() -> dict:
    """子进程跑报告生成器：隔离 DB/依赖，且生成失败不影响主流程。"""
    return await asyncio.to_thread(_generate_report_sync)


async def daily_job():
    """每日全流程：抓取 → 循环解读消化积压 → 生成执行报告并推送。"""
    from .crawler.runner import run_fetch
    from .ai.pipeline import run_interpret

    log.info("daily job start")
    await run_fetch()
    if config.ai_enabled():
        for _ in range(50):  # 最多消化 50 批，批大小可配（INTERPRET_BATCH_SIZE）
            r = await asyncio.to_thread(run_interpret, 0)
            if r["processed"] == 0:
                break
    log.info("daily job done")
    # 报告与推送是非阻断步骤：失败只记日志，不影响本轮抓取/解读结果
    try:
        res = await generate_report_and_notify()
        log.info("execution report generated: %s", str(res)[:300])
    except Exception:  # noqa: BLE001
        log.exception("execution report generation/notify failed (non-fatal)")


def start_scheduler():
    # 每天按 CRON_HOURS 多个时刻触发（如 6,12,21 → 每天 3 次）。
    # misfire_grace_time=3600：触发点错过后 1 小时内仍补跑（防止进程被系统
    # 短暂节流/挂起导致任务被静默跳过）；coalesce=True：多次错过只补跑一次。
    hours = ",".join(str(h) for h in config.CRON_HOURS)
    # 直接注册协程函数：AsyncIOExecutor 会在 event loop 里 await 它。
    # 不要用 lambda + asyncio.ensure_future —— 同步函数会被丢进线程池，
    # 那里没有 running loop，ensure_future 抛 RuntimeError 且任务不执行。
    scheduler.add_job(
        daily_job,
        "cron", hour=hours, minute=config.CRON_MINUTE, id="daily",
        misfire_grace_time=3600, coalesce=True, replace_existing=True,
    )
    if not scheduler.running:
        scheduler.start()
    jobs = scheduler.get_jobs()
    times = ", ".join(f"{h:02d}:{config.CRON_MINUTE:02d}" for h in config.CRON_HOURS)
    for j in jobs:
        log.info("scheduler job %s next_run=%s", j.id, j.next_run_time)
    if not jobs:
        log.error("scheduler started but NO jobs registered — 定时任务不会执行")
    else:
        log.info("scheduler started (cron %s, %d job(s))", times, len(jobs))
