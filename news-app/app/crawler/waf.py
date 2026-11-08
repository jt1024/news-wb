"""WAF / 反爬 JS 挑战的通用求解，按域名缓存通行 Cookie 头。

支持三类挑战，都统一输出一条可直接用于 Cookie 头的字符串：

1. **创宇盾 521（ydclearance）**——梅州等地市站。521 + 内联混淆 JS，
   执行后给出 ``https_ydclearance=...``。用 quickjs（纯 pip 依赖）同步求解。
2. **创宇盾新版 412（WZWS）**——国家卫健委、国家药监局。412 + ``$_ts``
   动态 VM + 外链 100KB+ 混淆 JS，quickjs 缺少完整 DOM 无法解；
   改用本机 Chrome headless + CDP 让浏览器自己跑完挑战，再取回 cookie。
   没有 Chrome 时该源本轮失败，不影响其它源。
3. **EO_Bot_Ssid 200 挑战**——人社部。返回 200 但正文只有一段内联 JS，
   执行后写 ``__tst_status`` / ``EO_Bot_Ssid`` 两个 cookie。quickjs 求解。

cookie 与出口 IP + UA 绑定：求解与后续请求共用 config.USER_AGENT。
412 类 cookie 有效期很短（实测十几分钟），TTL 到点自动重新预热；
HTTP 层遇到 412 也会强制刷新一次。
"""
import asyncio
import json
import logging
import re
import shutil
import socket
import tempfile
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
import quickjs

from .. import config

log = logging.getLogger("crawler.waf")

# 挑战页特征：521 状态 + window.onload=setTimeout("fn(N)"... + 字节数组 oo
_CHALLENGE_SCRIPT_RE = re.compile(r"<script[^>]*>([\s\S]*?window\.onload[\s\S]*?)</script>")

# 域名 -> (完整 Cookie 头, 过期时间戳)
_clearance: dict[str, tuple[str, float]] = {}
# 同一域名同时只允许一个 Chrome 预热，避免并发拉起一堆浏览器
_wzws_locks: dict[str, asyncio.Lock] = {}
# 域名 -> 复用的 Chrome CDP 会话；412 站点在一次抓取轮次内只启动一次浏览器
_chrome_sessions: dict[str, "_ChromeTab"] = {}
# Chrome 预热时顺带渲染好的页面：URL -> (html, 时间戳)，调用方取走即删
_chrome_html: dict[str, tuple[str, float]] = {}


# ---------------- 缓存 ----------------

def cookie_header(url: str) -> str | None:
    """返回该域名下缓存的完整 Cookie 头；无缓存/已过期返回 None。"""
    host = _host_of(url)
    entry = _clearance.get(host)
    if not entry:
        return None
    ck, expires = entry
    if time.time() > expires:
        _clearance.pop(host, None)
        return None
    return ck


def _cache(host: str, cookie: str, ttl: float) -> str:
    _clearance[host] = (cookie, time.time() + max(ttl, 60))
    return cookie


def invalidate(url: str) -> None:
    """丢弃该域名的 cookie（收到新的挑战页时调用，强制重新求解）。"""
    _clearance.pop(_host_of(url), None)


# Cookie 属性，不能当成 cookie 名写进请求
_COOKIE_ATTRS = {"path", "domain", "expires", "max-age", "samesite",
                 "secure", "httponly", "priority"}


def apply_cookie(client, url: str) -> None:
    """把缓存的 Cookie 头注入 httpx client（可能含多个 cookie）。"""
    ck = cookie_header(url)
    if not ck:
        return
    host = urlparse(url).hostname or ""
    for part in ck.split(";"):
        name, sep, value = part.strip().partition("=")
        if name and sep and name.lower() not in _COOKIE_ATTRS:
            client.cookies.set(name, value, domain=host)


def take_chrome_html(url: str) -> str | None:
    """取走 Chrome 预热时渲染出的页面 HTML（一次性，2 分钟内有效）。"""
    entry = _chrome_html.pop(url, None)
    if not entry:
        return None
    html, ts = entry
    return html if html and time.time() - ts < 120 else None


# ---------------- 1. 创宇盾 521 ----------------

def is_challenge(status_code: int, body: str) -> bool:
    """识别 ydclearance 挑战页（特征足够独特，不会误伤正常页面）。"""
    return status_code == 521 and "window.onload" in body and "oo = [" in body


def solve(url: str, challenge_html: str) -> str | None:
    """解 521 挑战页，缓存并返回 Cookie 头。失败返回 None。"""
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
    return _cache(host, f"{name}={value}", min(expires - time.time(), 3600))


def _run_challenge_js(html: str) -> str | None:
    """在 quickjs 里执行 521 挑战脚本，返回 document.cookie 被赋的值。"""
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


# ---------------- 2. 创宇盾新版 412 ----------------

def is_wzws_challenge(status_code: int, body: str) -> bool:
    """412 + $_ts 动态挑战（卫健委 / 药监局）。"""
    return status_code == 412 and "$_ts" in body and "r='m'" in body


async def solve_wzws(url: str, force: bool = False) -> str | None:
    """用本机 Chrome headless 跑完 412 挑战并返回 Cookie 头。

    Chrome 不可用 / 超时 / 被 WAF 拒绝时返回 None——调用方该源本轮失败，
    绝不阻塞其它源。force=True 用于收到新挑战页时强制重新预热。
    """
    host = _host_of(url)
    lock = _wzws_locks.setdefault(host, asyncio.Lock())
    async with lock:
        if not force:
            cached = cookie_header(url)
            if cached:
                return cached
        try:
            ck = await asyncio.wait_for(
                _chrome_clearance(url), timeout=config.WAF_CHROME_TIMEOUT
            )
        except asyncio.TimeoutError:
            log.warning("WAF Chrome clearance timeout for %s", host)
            return None
        except Exception as e:
            log.warning("WAF Chrome clearance failed for %s: %s", host, str(e)[:160])
            return None
        if ck:
            log.info("WAF 412 clearance solved for %s", host)
        return ck


class _ChromeTab:
    """一个可复用的 headless Chrome CDP 会话（按域名缓存）。

    412 站点的通行 token 常与单个 URL 绑定，httpx 拿 cookie 重放无法跨页面复用；
    因此每个 URL 都由浏览器自己访问一遍，直接取回渲染后的 HTML，
    一遍顺带收集 cookie。整个轮次只启动一次 Chrome。
    """

    def __init__(self, proc, ws, profile: str):
        self.proc, self.ws, self.profile = proc, ws, profile
        self.seq = 0
        self.expires = time.time() + config.WAF_COOKIE_TTL

    def dead(self) -> bool:
        if self.proc.returncode is not None or time.time() > self.expires:
            return True
        state = getattr(self.ws, "state", None)
        return state is not None and getattr(state, "name", "") == "CLOSED"

    async def cmd(self, method: str, params: dict | None = None) -> dict:
        self.seq += 1
        mine = self.seq
        await self.ws.send(json.dumps({"id": mine, "method": method,
                                       "params": params or {}}))
        while True:  # 事件消息先到，只认自己那条响应
            msg = json.loads(await asyncio.wait_for(self.ws.recv(), 20))
            if msg.get("id") == mine:
                return msg.get("result", {})

    async def navigate(self, url: str) -> str:
        await self.cmd("Page.navigate", {"url": url})
        deadline = time.time() + config.WAF_CHROME_WAIT
        while True:
            await asyncio.sleep(0.5)
            r = await self.cmd("Runtime.evaluate", {
                "expression": "document.documentElement.outerHTML",
                "returnByValue": True,
            })
            html = ((r.get("result") or {}).get("value") or "")
            # 挑战页含 $_ts；页面 reload 成真实内容后立即返回，不必等满 6 秒
            if html and len(html) > 1000 and "$_ts" not in html[:8000]:
                return html
            if time.time() >= deadline:
                return html

    async def cookies(self, host: str) -> list[dict]:
        r = await self.cmd("Network.getAllCookies")
        out = []
        for c in r.get("cookies", []):
            domain = (c.get("domain") or "").lstrip(".")
            if domain and (host == domain or host.endswith("." + domain)):
                out.append(c)
        return out

    async def close(self) -> None:
        try:
            await self.ws.close()
        except Exception:
            pass
        if self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except Exception:
                self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


async def _get_tab(host: str) -> "_ChromeTab | None":
    for h, t in list(_chrome_sessions.items()):
        if t.dead():
            await t.close()
            _chrome_sessions.pop(h, None)
    tab = _chrome_sessions.get(host)
    if tab:
        return tab

    chrome = config.CHROME_PATH
    if not Path(chrome).exists():
        log.warning("Chrome 不存在，跳过 412 挑战求解：%s", chrome)
        return None
    try:
        from websockets.asyncio.client import connect
    except ImportError:  # 老版本 websockets
        from websockets.client import connect

    port = _free_port()
    profile = tempfile.mkdtemp(prefix="waf_chrome_")
    proc = None
    ws = None
    try:
        proc = await asyncio.create_subprocess_exec(
            chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled",
            f"--user-agent={config.USER_AGENT}",
            f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
            "about:blank",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{port}"
        # 必须关掉 trust_env：环境里的 HTTP_PROXY 会把 127.0.0.1 的 CDP 请求
        # 也转发到代理，返回 502 upstream connect failed。
        async with httpx.AsyncClient(timeout=2, trust_env=False) as http:
            for _ in range(40):
                try:
                    await http.get(base + "/json/version")
                    break
                except Exception:
                    await asyncio.sleep(0.25)
            else:
                log.warning("Chrome CDP 未就绪 %s", host)
                raise RuntimeError("CDP not ready")
            info = (await http.put(base + "/json/new?about:blank")).json()
        ws = await connect(info["webSocketDebuggerUrl"], max_size=8 * 1024 * 1024)
        tab = _ChromeTab(proc, ws, profile)
        await tab.cmd("Page.enable")
        await tab.cmd("Network.enable")
        await tab.cmd("Runtime.enable")
        _chrome_sessions[host] = tab
        return tab
    except Exception as e:
        log.warning("Chrome CDP 会话启动失败 %s: %s", host, str(e)[:160])
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except Exception:
                proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        return None


async def _chrome_clearance(url: str) -> str | None:
    host = _host_of(url)
    tab = await _get_tab(host)
    if tab is None:
        return None
    try:
        html = await tab.navigate(url)
        if html and "$_ts" not in html[:8000]:
            _chrome_html[url] = (html, time.time())
        cookies = await tab.cookies(host)
    except Exception as e:
        log.warning("Chrome 预热失败 %s: %s", host, str(e)[:160])
        tab.expires = 0  # 下次重建会话
        return None
    if not cookies:
        log.warning("Chrome 未生成 412 通行 cookie：%s", host)
        return None
    return _cache(host,
                  "; ".join(f"{c['name']}={c['value']}" for c in cookies),
                  config.WAF_COOKIE_TTL)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------- 3. EO_Bot_Ssid 200 挑战 ----------------

def is_eo_challenge(status_code: int, body: str) -> bool:
    """人社部：HTTP 200 但整页只有一段设置 EO_Bot_Ssid 的 JS。"""
    return (status_code == 200 and len(body) < 8000
            and "EO_Bot_Ssid" in body and "document[" in body)


def solve_eo(url: str, body: str) -> str | None:
    """用 quickjs 解 EO_Bot_Ssid 内联挑战，返回 Cookie 头。"""
    m = re.search(r"<script[^>]*>([\s\S]*?)</script>", body)
    if not m:
        return None
    ctx = quickjs.Context()
    ctx.eval(
        "var __ck = [];"
        "var document = {"
        "  set cookie(v) { __ck.push(String(v)); },"
        "  get cookie() { return __ck.join('; '); }"
        "};"
        "var location = { href: '' };"
        "var window = this;"
        "function setTimeout(fn, ms) {}"   # 挑战最后会 reload，不需要执行
        "function clearTimeout() {}"
    )
    try:
        ctx.eval(m.group(1))
        values = json.loads(ctx.eval("JSON.stringify(__ck)"))
    except Exception as e:
        log.warning("EO challenge JS failed for %s: %s", _host_of(url), str(e)[:120])
        return None
    parts = [v.strip().rstrip(";") for v in values if "=" in v]
    if not parts:
        return None
    return _cache(_host_of(url), "; ".join(parts), 3600)


# ---------------- 公共 ----------------

def _parse_expires(raw_cookie: str) -> float | None:
    m = re.search(r"expires=([^;]+)", raw_cookie)
    if not m:
        return None
    try:
        return parsedate_to_datetime(m.group(1).strip()).timestamp()
    except (ValueError, TypeError):
        return None


def _host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()
