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
    publish_time: datetime | None = None  # 列表页缺日期时从详情页 meta 兜底


DATE_PATTERNS = [
    r"(20\d{2})-(\d{1,2})-(\d{1,2})",
    r"(20\d{2})年(\d{1,2})月(\d{1,2})日?",
    r"(20\d{2})/(\d{1,2})/(\d{1,2})",
    r"(20\d{2})\.(\d{1,2})\.(\d{1,2})",
]

# 中央部委列表页常不显示日期，但 URL 里带发布日期：
#   /20261105/<hash>/c.html（能源局）、/202611/t20261105_123.htm（财政部/农业农村部）
#   /art/2026/9/23/art_14_123.html（医保局）
URL_DATE_PATTERNS = [
    re.compile(r"/(20\d{2})(\d{2})(\d{2})/"),
    re.compile(r"/t(20\d{2})(\d{2})(\d{2})_"),
    re.compile(r"/(20\d{2})/(\d{1,2})/(\d{1,2})/art_"),
    # 中央港澳办：/2026/11/02/ARTIxxxx.shtml（大写 ARTI，无 art_ 前缀）
    re.compile(r"/(20\d{2})/(\d{1,2})/(\d{1,2})/"),
]

DETAIL_DATE_META_RE = re.compile(
    r"pubdate|publishdate|publish_time|published_time|datepublished|docrelpubtime", re.I
)

# 版式噪音行（详情页头部/尾部的导航与排版元素，整行剔除）
NOISE_TEXT_RE = re.compile(
    r"^(?:分享到[:：].*|分享|微信扫一扫.*|扫一扫.*|打印|本站有|【打印】|【关闭】|关闭页面|关闭|"
    r"版权所有|粤ICP备|粤公网安.*|主办[:：].*|承办[:：].*|"
    r"网站地图|无障碍|长者模式|来源[:：].{0,30}|信息来源[:：].{0,30}|浏览字体.*|【浏览字体.*|"
    r"当前位置[:：].*|发布时间[:：].*|发布日期[:：].*|时间[:：].*|作者[:：]?.*|阅读人次?.*|阅读\d*|"
    r"【?字体.*|字体大小|默认|字号[:：]?.*|【?TOP】?|[】【\[\s]*|大|中|小|超大)$"
)

# 部委详情页的公文元数据表格：标签与值各占一行（药监局 XZXK-2026-xxxxx）
META_LINE_RE = re.compile(
    r"^(?:索引号|索\s*引\s*号|主题分类|标题|文号|发布机构|发文机关|发文日期|"
    r"成文日期|时效性|体裁|主题词|有效性|发布日期|发布时间)(?:[:：].*)?$"
    r"|^[A-Z]{2,}[-－]\d{4}[-－]\d+.*$"
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
        if (NOISE_TEXT_RE.match(s) or BREADCRUMB_RE.match(s)
                or DATE_LINE_RE.match(s) or META_LINE_RE.match(s)):
            continue
        # 无实质内容的短行（孤立符号/分享按钮组等）
        if re.fullmatch(r"[\W_\s　]*(?:分享|微信|微博|QQ|更多)?[\W_\s　]*", s):
            continue
        if not re.search(r"[\u4e00-\u9fff]", s) and len(s) < 6:
            continue
        # 部分部委正文容器把站点域名单独渲染成一行（科技部 www.most.gov.cn）
        if re.fullmatch(r"(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:\.cn|\.com)?", s, re.I):
            continue
        # 去掉行内残留的浏览字体标记
        s = re.sub(r"【?浏览字体[:：]?[^】]*】?", "", s).strip()
        if s:
            out.append(s)
    out = _strip_leading_junk(out)
    # 部委公文表格会把标题重复渲染成一行（药监局），前几行同文只保留首次
    seen: set[str] = set()
    deduped = []
    for i, ln in enumerate(out):
        if i < 8 and len(ln) >= 8:
            if ln in seen:
                continue
            seen.add(ln)
        deduped.append(ln)
    return deduped


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
    """清洗列表页标题：剥 HTML 标签（如 <br/>）、解码实体（&quot; 等）、压缩空白。

    部分部委（交通运输部）把发布日期直接拼在链接文本尾部，标题里会拖一条
    「2026-11-06」尾巴，剥掉避免污染标题指纹与展示。
    """
    t = re.sub(r"<[^>]+>", " ", str(raw))
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"[\s　]*20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2}日?\s*$", "", t).strip()


# 公共后缀：不能作为「父域」把不相干的政务站串成同站
PUBLIC_SUFFIXES = {
    "cn", "com", "net", "org", "gov.cn", "com.cn", "org.cn", "net.cn",
    "ac.cn", "edu.cn", "mil.cn", "gov.hk", "edu.hk",
}


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
    if h == b or h.endswith("." + b):
        return True
    # b 是 h 的子域时才反向放行。但 gov.cn / com.cn 这类是公共后缀：
    # 若不拦住，"samr.gov.cn".endswith(".gov.cn") 会让市场监管总局首页把
    # 中国政府网的通稿当成本部新闻抓进来（所有政务站都同属 .gov.cn）。
    if h in PUBLIC_SUFFIXES:
        return False
    return b.endswith("." + h)


def _parse_date(text: str) -> datetime | None:
    for pat in DATE_PATTERNS:
        m = re.search(pat, text)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
    return None


def _parse_date_from_url(url: str) -> datetime | None:
    """从详情页 URL 里抽取精确发布日期（列表页无日期时的第一层兜底）。"""
    for pat in URL_DATE_PATTERNS:
        m = pat.search(url)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
    return None


def _detail_publish_date(soup: BeautifulSoup, raw_html: str) -> datetime | None:
    """详情页日期兜底：优先 meta 标签，其次带「发布时间」标签的短文本。

    不从正文里随便抓第一个日期——政策原文常引用历史年份，会错标发布时间。
    """
    for m in soup.find_all("meta"):
        key = m.get("name") or m.get("property") or m.get("itemprop") or ""
        if DETAIL_DATE_META_RE.search(str(key)):
            d = _parse_date(str(m.get("content") or ""))
            if d:
                return d
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw_html))
    m = re.search(
        r"(?:发布时间|发布日期|发表时间|信息来源|来源)\s*[:：]?\s*"
        r"(20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2})", text[:20000]
    )
    return _parse_date(m.group(1)) if m else None


class Fetcher:
    """一个源站点对应一个 Fetcher 实例。"""

    def __init__(self, source):
        self.source = source
        self.selectors = source.selector_config or {}

    # 极少数站点尚未启用 https（实测 https 握手直接失败），保留明文访问。
    # 海关总署的 https 是自签证书链且回 504，只有 http 明文能返回完整页面。
    HTTP_ONLY_HOSTS = {"www.maoming.gov.cn", "www.jieyang.gov.cn",
                       "gd.tobacco.gov.cn", "www.customs.gov.cn"}

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
            # 创宇盾 521（ydclearance）：quickjs 解内联挑战后重放
            if waf.is_challenge(resp.status_code, resp.text):
                log.warning("WAF 521 challenge on %s, solving", url)
                if waf.solve(url, resp.text):
                    waf.apply_cookie(client, url)
                    resp = await client.get(url)
            # 创宇盾新版 412（WZWS）：混淆 VM 需完整 DOM，交给本机 Chrome headless
            elif waf.is_wzws_challenge(resp.status_code, resp.text):
                log.warning("WAF 412 challenge on %s, warming via Chrome", url)
                waf.invalidate(url)
                if await waf.solve_wzws(url, force=True):
                    # 412 通行 token 常与单个 URL 绑定，cookie 重放未必放行；
                    # 优先用浏览器渲染好的同一 URL 页面，一步到位。
                    rendered = waf.take_chrome_html(url)
                    if rendered:
                        return rendered
                    waf.apply_cookie(client, url)
                    resp = await client.get(url)
            # 人社部：200 但整页只有设置 EO_Bot_Ssid 的挑战 JS
            elif waf.is_eo_challenge(resp.status_code, resp.text):
                log.warning("EO bot challenge on %s, solving", url)
                if waf.solve_eo(url, resp.text):
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
        enc = (resp.encoding or "utf-8").lower()
        if enc == "utf-8":
            return resp.text
        # GB2312/GBK 是 GB18030 的子集，国台办等站点按窄字符集声明，
        # 直接用大字符集解码可避免生僻字触发 UnicodeDecodeError。
        if enc in ("gb2312", "gbk", "gb-2312", "gb_2312"):
            enc = "gb18030"
        try:
            return resp.content.decode(enc)
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
        """解析 JSON 接口列表。

        兼容四种格式：
        - 珠海 postmeta：{"articles": [{"title","url","publish_time": 时间戳}]}
        - 中国政府网静态列表：顶层数组 [{"TITLE","URL","DOCRELPUBTIME": "2026-11-07"}]
        - 金融监管总局：{"data":{"rows":[{"docTitle","publishDate","docId"}]}}
          这类接口不返回 URL，用 selector_config.url_template 按字段拼详情页地址。
        """
        import json

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("json list parse failed for %s", self.source.name)
            return []
        payload = (data.get("data") if isinstance(data, dict) else None) or {}
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = (data.get("articles") or data.get("list")
                    or payload.get("articles") or payload.get("rows") or [])
        else:
            rows = []
        items = []
        base = self.source.base_url or self.source.list_url
        url_template = self.selectors.get("url_template") or ""
        for a in rows:
            if not isinstance(a, dict):
                continue
            title = _clean_title(str(a.get("title") or a.get("TITLE")
                                     or a.get("docTitle") or a.get("docSubtitle") or ""))
            if url_template:
                url = re.sub(r"\{(\w+)\}",
                             lambda m: str(a.get(m.group(1)) or ""), url_template)
            else:
                url = str(a.get("url") or a.get("URL") or a.get("link")
                          or a.get("linked_url") or "").strip()
            url = self._prefer_https(url)
            if not title or not url or len(title) < 8:
                continue
            # 政府网 JSON 里混有新华网/央视外链，只保留源站文章
            if not same_site(url, base):
                continue
            pub = None
            ts = (a.get("publish_time") or a.get("DOCRELPUBTIME")
                  or a.get("pubDate") or a.get("first_publish_time")
                  or a.get("publishDate"))
            if isinstance(ts, (int, float)) and ts > 10**12:
                pub = datetime.fromtimestamp(ts / 1000)
            elif isinstance(ts, (int, float)) and ts > 10**9:
                pub = datetime.fromtimestamp(ts)
            elif ts:
                pub = _parse_date(str(ts))
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
            # 中央部委站大量使用 .htm 后缀（财政部 / 农业农村部 / 中国政府网），
            # 旧规则只认 .html|.shtml，会把整页新闻全部滤掉。
            if not re.search(r"(post_|content/|art/|\.(html|shtml|htm)$)", url):
                continue
            # 栏目首页（/index.html、/index_2.html 等）不是新闻详情，
            # 抓进来只会得到机构名标题 + 空正文，直接排除。
            # 但人民银行把每篇文章放在独立数字目录里，详情页恰是 /<14位时间戳>/index.html，
            # 这类带长数字 ID 的路径是文章，必须放行。
            is_index = re.search(r"/index(_\d+)?\.(html?|shtml|htm)$", url, re.I)
            has_article_id = re.search(r"/\d{8,}/", url) or re.search(
                r"(t20\d{6}_\d+|art_[0-9a-f]{16,}|content_\d+)", url, re.I
            )
            if is_index and not has_article_id and not re.search(r"(post_|content/|art/)", url):
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
                pub = _parse_date(str(a)) or _parse_date_from_url(url)
            items.append(ListItem(url=url, title=title, publish_time=pub))
        return items

    # ---- 详情页 ----
    async def fetch_detail(self, url: str) -> Detail:
        # 金融监管总局的 ItemDetail.html 是 JS 空壳，正文在 SelectByDocId 接口里。
        # 配置 detail_api_template 时把详情页 URL 里的 docId 映射到接口。
        tmpl = self.selectors.get("detail_api_template") or ""
        m = re.search(r"docId=(\d+)", url) if tmpl else None
        async with self._client() as client:
            await asyncio.sleep(config.FETCH_DELAY_SECONDS)
            if m:
                raw = await self.get(client, tmpl.format(docId=m.group(1)))
                return self._extract_api_detail(raw)
            html = await self.get(client, url)
        return self._extract_detail(html)

    @staticmethod
    def _extract_api_detail(raw: str) -> Detail:
        """解析 JSON 详情接口的 docClob（Word 粘贴的 HTML 片段）。"""
        import json

        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return Detail()
        payload = data.get("data") if isinstance(data, dict) else None
        if not isinstance(payload, dict):
            return Detail()
        pub = _parse_date(str(payload.get("publishDate") or ""))
        body = payload.get("docClob") or payload.get("content") or ""
        if not body:
            return Detail(publish_time=pub)
        soup = BeautifulSoup(body, "lxml")
        for t in soup(["script", "style", "nav", "header", "footer", "iframe", "form"]):
            t.decompose()
        # Word 粘贴的 HTML 会把一句话拆进多个 <span>（「为 进一步完善 保险 公司」），
        # 按空格合并而非逐行切分，再清掉汉字之间被插入的空格。
        text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
        text = re.sub(r"(?<=[\u4e00-\u9fff，。、；：（）])\s+"
                      r"(?=[\u4e00-\u9fff，。、；：（）])", "", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        text = "\n".join(_clean_text_lines([text])) if text else ""
        return Detail(content_text=text, content_html=body, publish_time=pub)

    def _extract_detail(self, html: str) -> Detail:
        soup = BeautifulSoup(html, "lxml")
        pub = _detail_publish_date(soup, html)
        for t in soup(["script", "style", "nav", "header", "footer", "iframe", "form"]):
            t.decompose()

        node = None
        custom_content = self.selectors.get("content")
        for sel in (
            custom_content,
            "#zoom", "#zoombox", "#ivs_content", ".TRS_Editor",
            "#zoomcon", ".zw",  # 南方新闻网建站平台（广东多数地市通用）
            ".content_article", ".article-content", ".article", ".main-txt",
            ".conNews", ".detailCon", ".tyxl_nr_con", ".UCAP-CONTENT",
            "#content", ".content", "article",
        ):
            if not sel:
                continue
            node = soup.select_one(sel)
            # 显式配置的正文容器可信，任免公告之类 <80 字的短稿也要收；
            # 内置兜底选择器仍要求 80 字，避免误把导航块当正文。
            min_len = 20 if sel == custom_content else 80
            if node and len(node.get_text(strip=True)) > min_len:
                break
            node = None
        if node is None:
            node = self._heuristic_main_block(soup)
        if node is None:
            return Detail(publish_time=pub)
        raw = node.get_text("\n")
        if _is_footer_only(raw):
            return Detail(publish_time=pub)
        text = "\n".join(_clean_text_lines(raw.splitlines()))
        return Detail(content_text=text, content_html=str(node), publish_time=pub)

    @staticmethod
    def _heuristic_main_block(soup: BeautifulSoup):
        """启发式：取 <p> 文本量最大的容器。"""
        best, best_len = None, 0
        for cand in soup.find_all(["div", "section", "td"]):
            p_len = sum(len(p.get_text(strip=True)) for p in cand.find_all("p"))
            if p_len > best_len:
                best, best_len = cand, p_len
        return best if best_len > 80 else None
