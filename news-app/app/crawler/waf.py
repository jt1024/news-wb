"""创宇盾（ydclearance）JS 挑战的通用求解。

部分地市政府站点（首例：梅州 www.meizhou.gov.cn）在 WAF 后面，直接请求返回
521 + 一段混淆 JS：页面执行后算出通行 cookie（https_ydclearance=...）再重放。
本模块把那段 JS 丢进 quickjs（嵌入式 JS 引擎，纯 pip 依赖）同步执行，
取回 cookie 后按域名缓存复用（有效期内不再重复解）。

cookie 与出口 IP + UA 绑定：求解与后续请求必须用同一个 UA（config.USER_AGENT），
本服务所有请求都从本机发出，天然满足。
"""
import logging
import re
import time
from email.utils import parsedate_to_datetime

import quickjs

log = logging.getLogger("crawler.waf")

# 挑战页特征：521 状态 + window.onload=setTimeout("fn(N)"... + 字节数组 oo
_CHALLENGE_SCRIPT_RE = re.compile(r"<script[^>]*>([\s\S]*?window\.onload[\s\S]*?)</script>")

# 域名 -> (cookie名, cookie值, 过期时间戳)
_clearance: dict[str, tuple[str, str, float]] = {}


def is_challenge(status_code: int, body: str) -> bool:
    """识别 ydclearance 挑战页（特征足够独特，不会误伤正常页面）。"""
    return status_code == 521 and "window.onload" in body and "oo = [" in body


def cookie_header(url: str) -> str | None:
    """返回该 URL 域名下缓存的通行 cookie（"name=value"），无效/过期返回 None。"""
    host = _host_of(url)
    entry = _clearance.get(host)
    if not entry:
        return None
    name, value, expires = entry
    if time.time() > expires - 60:  # 提前 1 分钟视为过期
        _clearance.pop(host, None)
        return None
    return f"{name}={value}"


def apply_cookie(client, url: str) -> None:
    """把缓存的通行 cookie 注入 httpx client（没有缓存则不动）。"""
    from urllib.parse import urlparse

    ck = cookie_header(url)
    if ck:
        name, _, value = ck.partition("=")
        client.cookies.set(name, value, domain=urlparse(url).hostname or "")


def solve(url: str, challenge_html: str) -> str | None:
    """解挑战页，缓存并返回 "name=value" 通行 cookie。失败返回 None。"""
    host = _host_of(url)
    try:
        raw = _run_challenge_js(challenge_html)
    except Exception as e:  # quickjs 任何异常都不影响主流程
        log.warning("WAF challenge JS execution failed for %s: %s", host, str(e)[:120])
        return None
    if not raw:
        return None
    name, _, rest = raw.partition("=")
    value = rest.split(";", 1)[0].strip()
    if not name or not value:
        return None
    expires = _parse_expires(raw) or (time.time() + 3600)
    _clearance[host] = (name, value, expires)
    log.info("WAF clearance solved for %s (valid %.1fh)", host, (expires - time.time()) / 3600)
    return f"{name}={value}"


def _run_challenge_js(html: str) -> str | None:
    """在 quickjs 里执行挑战脚本，返回 document.cookie 被赋的值。"""
    m = _CHALLENGE_SCRIPT_RE.search(html)
    if not m:
        return None
    script = m.group(1)
    ctx = quickjs.Context()
    # 浏览器环境垫片：只需要 document.cookie 赋值这条路径。
    # 挑战 JS 会 setTimeout("fn(N)", 200) 延迟执行——同步立即 eval 即可；
    # 它随后还会尝试连环 reload，只放行第一次，防递归。
    ctx.eval(
        "var __ck = '';"
        "var document = {"
        "  set cookie(v) { __ck = v; },"
        "  get cookie() { return __ck; }"
        "};"
        "var location = { reload() {}, href: '' };"
        "var window = this;"
        "var __setTimeoutCalls = 0;"
        "function setTimeout(fn, ms) {"
        "  if (typeof fn === 'string' && __setTimeoutCalls++ < 3) { eval(fn); }"
        "}"
        "function clearTimeout() {}"
    )
    ctx.eval(script)
    return ctx.eval("__ck") or None


def _parse_expires(raw_cookie: str) -> float | None:
    m = re.search(r"expires=([^;]+)", raw_cookie)
    if not m:
        return None
    try:
        return parsedate_to_datetime(m.group(1).strip()).timestamp()
    except (ValueError, TypeError):
        return None


def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url).hostname or "").lower()
