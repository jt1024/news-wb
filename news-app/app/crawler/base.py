"""抓取器基类：列表页解析 + 详情页正文提取（配置驱动 + 通用启发式兜底）。"""
import asyncio
import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .. import config
from . import waf

log = logging.getLogger("crawler.base")


@dataclass
class ListItem:
    url: str
    title: str
    publish_time: datetime | None = None


@dataclass
class Detail:
    content_text: str = ""
    content_html: str = ""


DATE_PATTERNS = [
    r"(20\d{2})-(\d{1,2})-(\d{1,2})",
    r"(20\d{2})年(\d{1,2})月(\d{1,2})日?",
    r"(20\d{2})/(\d{1,2})/(\d{1,2})",
    r"(20\d{2})\.(\d{1,2})\.(\d{1,2})",
]

# 版式噪音行（详情页头部/尾部的导航与排版元素，整行剔除）
NOISE_TEXT_RE = re.compile(
    r"^(?:分享到[:：].*|分享|微信扫一扫.*|扫一扫.*|打印|本站有|【打印】|【关闭】|关闭页面|关闭|"
    r"版权所有|粤ICP备|粤公网安.*|主办[:：].*|承办[:：].*|"
    r"网站地图|无障碍|长者模式|来源[:：].{0,30}|信息来源[:：].{0,30}|浏览字体.*|【浏览字体.*|"
    r"当前位置[:：].*|发布时间[:：].*|发布日期[:：].*|时间[:：].*|作者[:：]?.*|阅读人次?.*|阅读\d*|"
    r"【?字体.*|字体大小|默认|字号[:：]?.*|【?TOP】?|[】【\[\s]*|大|中|小|超大)$"
)

# 面包屑片段（如「首页 > 要闻动态 > 潮州要闻」），出现在行首则剔除
BREADCRUMB_RE = re.compile(r"^(?:首页|要闻动态|政务动态|搜索|>$|>\s*$|\d+\s*)$")

# 孤立日期/时间行、孤立括号残留（发布时间已单独存字段，正文里无需保留）
DATE_LINE_RE = re.compile(r"^(?:】|\[|\]|20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2}日?(\s+\d{1,2}:\d{2}(:\d{2})?)?\s*)$")

# 页脚特征：启发式兜底偶尔会选中整页的版权/联系方式容器（尤其纯附件页），
# 短文本里同时出现两个以上页脚标志，就认定没有正文，交给上层抑制。
FOOTER_RE = re.compile(r"版权所有|ICP备|网站标识码|主办单位|主办[:：]|承办[:：]|联系电话[:：]|粤公网安")


def _is_footer_only(raw: str) -> bool:
    return len(raw.strip()) < 400 and len(FOOTER_RE.findall(raw)) >= 2


def _clean_text_lines(lines: list[str]) -> list[str]:
    """剔除噪音行：版式元素、面包屑、孤立标点与日期行。"""
    out = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if NOISE_TEXT_RE.match(s) or BREADCRUMB_RE.match(s) or DATE_LINE_RE.match(s):
            continue
        # 无实质内容的短行（孤立符号/分享按钮组等）
        if re.fullmatch(r"[\W_\s　]*(?:分享|微信|微博|QQ|更多)?[\W_\s　]*", s):
            continue
        if not re.search(r"[\u4e00-\u9fff]", s) and len(s) < 6:
            continue
        # 去掉行内残留的浏览字体标记
        s = re.sub(r"【?浏览字体[:：]?[^】]*】?", "", s).strip()
        if s:
            out.append(s)
    return _strip_leading_junk(out)


def _strip_leading_junk(lines: list[str], max_scan: int = 10) -> list[str]:
    """剥离正文开头的短导航残留（如栏目名「潮州要闻」）。

    正文首行通常是长标题或完整段落；开头的超短行且无句末标点的，视为导航残留。
    标题之后的短行（<12 字且无句读）多为来源/作者等元数据，若其后紧跟完整段落
    （>20 字），同样剥离（最多 4 行）。
    """
    i = 0
    for i, ln in enumerate(lines[:max_scan]):
        if len(ln) >= 12 or re.search(r"[。！？；]", ln):
            break
        i += 1
    # 标题后元数据行剥离：保留首行（标题），仅剔除其后的短元数据行
    j, skipped = i + 1, 0
    while j < len(lines) and skipped < 4:
        ln = lines[j]
        if len(ln) < 12 and not re.search(r"[。！？；：]", ln):
            j += 1
            skipped += 1
        else:
            break
    if j > i + 1 and j < len(lines) and len(lines[j]) > 20:
        return [lines[i]] + lines[j:]
    return lines[i:] if i < len(lines) else lines


def _clean_title(raw: str) -> str:
    """清洗列表页标题：剥 HTML 标签（如 <br/>）、解码实体（&quot; 等）、压缩空白。"""
    t = re.sub(r"<[^>]+>", " ", str(raw))
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def same_site(url: str, base_url: str) -> bool:
    """判断详情页 URL 是否属于源站（同主机或子域/父域）。

    列表页常混入「适老化无障碍服务」「友情链接」等图标外链，标题够长时会被
    当成新闻条目，抓详情页又必然失败。历史 728 篇入库文章的主机全部与源站
    一致，因此同站过滤是安全的。主机解析不出来时放行，避免误杀相对/异常 URL。
    """
    h = (urlparse(url).hostname or "").lower().removeprefix("www.")
    b = (urlparse(base_url).hostname or "").lower().removeprefix("www.")
    if not h or not b:
        return True
    return h == b or h.endswith("." + b) or b.endswith("." + h)


def _parse_date(text: str) -> datetime | None:
    for pat in DATE_PATTERNS:
        m = re.search(pat, text)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
    return None


class Fetcher:
    """一个源站点对应一个 Fetcher 实例。"""

    def __init__(self, source):
        self.source = source
        self.selectors = source.selector_config or {}

    # 极少数站点尚未启用 https（实测 https 握手直接失败），保留明文访问
    HTTP_ONLY_HOSTS = {"www.maoming.gov.cn", "www.jieyang.gov.cn", "gd.tobacco.gov.cn"}

    @staticmethod
    def _prefer_https(url: str) -> str:
        """政府站点普遍已支持 https，统一升级；明文 http 易被网关/WAF 拦成 403。"""
        if not url.startswith("http://"):
            return url
        host = (urlparse(url).hostname or "").lower()
        if host in Fetcher.HTTP_ONLY_HOSTS:
            return url
        return "https://" + url[len("http://"):]

    # ---- HTTP ----
    def _client(self):
        return httpx.AsyncClient(
            headers={
                "User-Agent": config.USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
            timeout=config.FETCH_TIMEOUT,
            follow_redirects=True,
        )

    async def get(self, client: httpx.AsyncClient, url: str) -> str:
        url = self._prefer_https(url)
        waf.apply_cookie(client, url)
        try:
            resp = await client.get(url)
            # 创宇盾 JS 挑战（521）：解出通行 cookie 后重放一次
            if resp.status_code == 521 and waf.is_challenge(resp.status_code, resp.text):
                log.warning("WAF challenge on %s, solving", url)
                if waf.solve(url, resp.text):
                    waf.apply_cookie(client, url)
                    resp = await client.get(url)
            resp.raise_for_status()
            return self._decode(resp)
        except (
            httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError,
            httpx.HTTPStatusError,
        ) as e:
            # 国密 TLS 不兼容、网关 403/429、WAF 挑战等：交给 curl 子进程直连兜底。
            # curl 走独立进程链路，能绕过 Python 侧的连接/代理限制。
            log.warning("httpx failed for %s (%s), fallback to curl", url, str(e)[:80])
            return await self._curl_get(url)

    @staticmethod
    def _decode(resp: httpx.Response) -> str:
        if resp.encoding is None or resp.encoding == "utf-8":
            return resp.text
        try:
            return resp.content.decode(resp.encoding)
        except (UnicodeDecodeError, LookupError):
            return resp.text

    async def _curl_get(self, url: str) -> str:
        # -w 把状态码写在末尾分隔符后，避免把 403/WAF 挑战页当成正文入库
        marker = "\n__CURL_HTTP_CODE__:"
        cmd = [
            "curl", "-sS", "-L", "--compressed", "-m", str(config.FETCH_TIMEOUT),
            "-A", config.USER_AGENT, "-H", "Accept-Language: zh-CN,zh;q=0.9",
            "-w", marker + "%{http_code}", url,
        ]
        ck = waf.cookie_header(url)
        if ck:
            cmd[1:1] = ["-b", ck]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"curl failed: {stderr.decode(errors='ignore')[:200]}")
        for enc in ("utf-8", "gb18030"):
            try:
                text = stdout.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = stdout.decode("utf-8", errors="ignore")
        if marker in text:
            body, _, code = text.rpartition(marker)
            code = code.strip()[:3]
            if not code.startswith("2"):
                raise RuntimeError(f"HTTP {code} for {url}")
            text = body
        return text

    # ---- 列表页 ----
    async def fetch_list(self, max_items: int = 50) -> list[ListItem]:
        if self.source.fetch_type == "json":
            # 列表来自 JSON 接口（如珠海 postmeta），URL 放在 selector_config.list_api
            api = (self.selectors.get("list_api") or self.source.list_url)
            async with self._client() as client:
                raw = await self.get(client, api)
            return self._parse_json_list(raw)[:max_items]
        async with self._client() as client:
            html = await self.get(client, self.source.list_url)
        if self.source.fetch_type == "rss":
            return self._parse_rss(html)[:max_items]
        return self._parse_list(html)[:max_items]

    def _parse_json_list(self, raw: str) -> list[ListItem]:
        """解析 JSON 接口列表（兼容珠海 postmeta 格式：articles[].title/url/publish_time）。"""
        import json

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("json list parse failed for %s", self.source.name)
            return []
        items = []
        for a in data.get("articles") or data.get("data", {}).get("articles") or []:
            title = _clean_title(str(a.get("title", "")))
            url = self._prefer_https(str(a.get("url") or a.get("linked_url") or "").strip())
            if not title or not url or len(title) < 8:
                continue
            pub = None
            ts = a.get("publish_time") or a.get("first_publish_time")
            if isinstance(ts, (int, float)) and ts > 10**12:
                pub = datetime.fromtimestamp(ts / 1000)
            elif isinstance(ts, (int, float)) and ts > 10**9:
                pub = datetime.fromtimestamp(ts)
            items.append(ListItem(url=url, title=title, publish_time=pub))
        return items

    def _parse_rss(self, xml: str) -> list[ListItem]:
        import feedparser

        feed = feedparser.parse(xml)
        items = []
        for e in feed.entries:
            published = None
            if getattr(e, "published_parsed", None):
                import time

                published = datetime.fromtimestamp(time.mktime(e.published_parsed))
            items.append(ListItem(url=e.link, title=e.title, publish_time=published))
        return items

    def _parse_list(self, html: str) -> list[ListItem]:
        soup = BeautifulSoup(html, "lxml")
        sel = self.selectors.get("item") or "a"
        seen, items = set(), []
        for a in soup.select(sel):
            # 部分站点（如增城）链接写成 href=" http://..."，前导空格会让
            # urljoin 产出带空格的 URL，后续 httpx 报 UnsupportedProtocol。
            href = (a.get("href") or "").strip()
            title = _clean_title(a.get("title") or a.get_text())
            if not href or not title or len(title) < 8:
                continue
            url = self._prefer_https(urljoin(self.source.list_url, href))
            if not same_site(url, self.source.base_url or self.source.list_url):
                continue
            if not re.search(r"(post_|content/|art/|\.(html|shtml)$)", url):
                continue
            # 栏目首页（/index.html、/index_2.html 等）不是新闻详情，
            # 抓进来只会得到机构名标题 + 空正文，直接排除
            if (re.search(r"/index(_\d+)?\.(html?|shtml)$", url, re.I)
                    and not re.search(r"(post_|content/|art/)", url)):
                continue
            if url in seen:
                continue
            seen.add(url)
            # 日期：从链接的直接父容器逐层向上找（最多 3 层）。
            # 白云区把标题放 div.tit、日期放 div.box，只看父层会漏掉日期；
            # 逐层由内向外、并截断到 600 字符，避免误取到相邻条目的日期。
            pub, node = None, a.parent
            for _ in range(3):
                if node is None:
                    break
                block = str(node)
                # 整块里出现多条新闻链接 = 已经到了列表容器，再往上找只会
                # 把首条日期错配给所有条目，直接停。
                if block.count("content/post_") > 1:
                    break
                ctx = re.sub(r"<[^>]+>", " ", block)[:600]
                pub = _parse_date(ctx)
                if pub:
                    break
                node = node.parent
            if pub is None:
                pub = _parse_date(str(a))
            items.append(ListItem(url=url, title=title, publish_time=pub))
        return items

    # ---- 详情页 ----
    async def fetch_detail(self, url: str) -> Detail:
        async with self._client() as client:
            await asyncio.sleep(config.FETCH_DELAY_SECONDS)
            html = await self.get(client, url)
        return self._extract_detail(html)

    def _extract_detail(self, html: str) -> Detail:
        soup = BeautifulSoup(html, "lxml")
        for t in soup(["script", "style", "nav", "header", "footer", "iframe", "form"]):
            t.decompose()

        node = None
        for sel in (
            self.selectors.get("content"),
            "#zoom", "#zoombox", "#ivs_content", ".TRS_Editor",
            "#zoomcon", ".zw",  # 南方新闻网建站平台（广东多数地市通用）
            ".content_article", ".article-content", ".article", ".main-txt",
            ".conNews", ".detailCon", ".tyxl_nr_con", ".UCAP-CONTENT",
            "#content", ".content", "article",
        ):
            if not sel:
                continue
            node = soup.select_one(sel)
            if node and len(node.get_text(strip=True)) > 80:
                break
            node = None
        if node is None:
            node = self._heuristic_main_block(soup)
        if node is None:
            return Detail()
        raw = node.get_text("\n")
        if _is_footer_only(raw):
            return Detail()
        text = "\n".join(_clean_text_lines(raw.splitlines()))
        return Detail(content_text=text, content_html=str(node))

    @staticmethod
    def _heuristic_main_block(soup: BeautifulSoup):
        """启发式：取 <p> 文本量最大的容器。"""
        best, best_len = None, 0
        for cand in soup.find_all(["div", "section", "td"]):
            p_len = sum(len(p.get_text(strip=True)) for p in cand.find_all("p"))
            if p_len > best_len:
                best, best_len = cand, p_len
        return best if best_len > 80 else None
