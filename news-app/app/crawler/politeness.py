"""礼貌抓取：域名级最小间隔 + 随机抖动 + 限流退避。

设计目标：降低被政务站 WAF / 网关限流的概率。所有等待都是异步的，
不阻塞 event loop；状态按域名隔离，互不影响。

注意：这里只做「请求前节流」和「遇到 429/503 后退避」，不重试业务失败。
真正的一次请求失败仍由 runner 记入 FetchLog 并触发源级熔断。
"""
import asyncio
import logging
import random
import time
from urllib.parse import urlparse

from .. import config

log = logging.getLogger("crawler.politeness")

# host -> 下一次允许发起请求的时间戳（time.monotonic）
_next_allowed: dict[str, float] = {}

# 退避状态：host -> (截止时间戳, 当前退避级数)
_penalty: dict[str, tuple[float, int]] = {}


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def reset():
    """清空节流状态（测试用；生产不要在抓取中途调用）。"""
    _next_allowed.clear()
    _penalty.clear()


def is_penalized(url: str) -> bool:
    """域名是否处于限流退避期。"""
    item = _penalty.get(_host(url))
    return bool(item and item[0] > time.monotonic())


async def wait_turn(url: str):
    """等待到该域名允许发起下一次请求。带随机抖动，避免固定节奏被识别。

    并发安全：先把「下一次允许时间」占位推后，再 sleep。否则多个源并发时
    会读到同一个 target、一起醒来、同时打向同一域名，域名级限速形同虚设。
    """
    host = _host(url)
    if not host:
        return
    now = time.monotonic()
    target = max(now, _next_allowed.get(host, 0.0))
    item = _penalty.get(host)
    if item and item[0] > target:
        target = item[0]
    # 占位在 await 之前完成，后到的并发请求会读到推后后的时间并排队。
    jitter = random.uniform(0, max(0.0, config.DOMAIN_JITTER))
    gap = config.DOMAIN_MIN_INTERVAL + jitter
    _next_allowed[host] = target + gap
    if target > now:
        await asyncio.sleep(target - now)


def note_rate_limited(url: str):
    """记录一次 429/503，对该域名做指数退避（上限 30 分钟）。"""
    host = _host(url)
    if not host:
        return
    prev_level = _penalty.get(host, (0.0, 0))[1]
    level = min(prev_level + 1, 8)
    seconds = min(15 * (2 ** (level - 1)), 1800)
    until = time.monotonic() + seconds
    _penalty[host] = (until, level)
    _next_allowed[host] = max(_next_allowed.get(host, 0.0), until)
    log.warning("rate limited by %s, backoff %ds (level %d)", host, seconds, level)


def note_success(url: str):
    """成功响应后逐步消解退避级别，避免一次抖动后长期慢速。"""
    host = _host(url)
    if not host:
        return
    item = _penalty.get(host)
    if not item:
        return
    until, level = item
    if level <= 1 or until <= time.monotonic():
        _penalty.pop(host, None)
    else:
        _penalty[host] = (until, level - 1)


def stats() -> dict:
    """导出当前状态供自检；不泄露具体 URL。"""
    return {
        "tracked_hosts": len(_next_allowed),
        "penalized_hosts": sum(1 for t, _ in _penalty.values() if t > time.monotonic()),
    }
