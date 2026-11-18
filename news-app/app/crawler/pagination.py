"""列表页分页 URL 生成。

政务站分页规则五花八门，无法一套正则通吃。这里按优先级：
1. selector_config.page_pattern：显式模板，{page} 占位（如 index_{page}.html、?page={page}）；
2. 从 list_url 的常见形态自动推导（index.html / index.shtml / 末尾斜杠）；
3. 推导不出来返回 None —— 该源只抓第一页，不猜、不乱试，避免打 404 骚扰站点。

自动推导仅覆盖最常见的 TRS WCM 风格：index.html → index_2.html（第 1 页无后缀）。
page=1 永远返回原始 list_url。
"""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def page_url(list_url: str, page: int, selector_config: dict | None = None) -> str | None:
    """返回第 page 页列表 URL；page=1 返回原 URL；无法确定返回 None。"""
    if page <= 1:
        return list_url
    cfg = selector_config or {}

    pattern = cfg.get("page_pattern") or ""
    if pattern:
        if "{page}" not in pattern:
            return None
        return pattern.replace("{page}", str(page))

    parts = urlsplit(list_url)
    path, query = parts.path, parts.query
    name = path.rsplit("/", 1)[-1]

    m = re.fullmatch(r"index(\.\w+)?", name)
    if m:
        ext = m.group(1) or ".html"
        new_name = f"index_{page}{ext}"
        new_path = path[:len(path) - len(name)] + new_name
        return urlunsplit((parts.scheme, parts.netloc, new_path, query, parts.fragment))

    if not name and path.endswith("/"):
        return urlunsplit((parts.scheme, parts.netloc, path + f"index_{page}.html",
                           query, parts.fragment))

    if query and "page=" not in query:
        params = parse_qsl(query, keep_blank_values=True)
        params.append(("page", str(page)))
        return urlunsplit((parts.scheme, parts.netloc, path,
                           urlencode(params), parts.fragment))

    return None


def is_same_first_url(a: str, b: str) -> bool:
    """两页返回的首条 URL 相同 => 分页没生效，应停止继续翻。"""
    return bool(a) and a == b
