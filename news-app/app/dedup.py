"""三层去重：URL 归一化哈希 / 标题指纹与相似度 / 正文 SimHash。"""
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "spm", "from", "share_token", "t", "timestamp",
}


def normalize_url(url: str) -> str:
    """URL 归一化：统一协议/域名小写、去默认端口、去跟踪参数、去 fragment 与尾斜杠。"""
    url = url.strip()
    p = urlparse(url)
    scheme = "https"
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if netloc.endswith(":80") or netloc.endswith(":443"):
        netloc = netloc.rsplit(":", 1)[0]
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query_pairs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS]
    query = urlencode(sorted(query_pairs))
    return urlunparse((scheme, netloc, path, "", query, ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def normalize_title(title: str) -> str:
    """标题归一化：去空白与标点，全角转半角，小写。"""
    title = title.translate(str.maketrans("０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
                                          "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"))
    return PUNCT_RE.sub("", title).lower()


def title_hash(title: str) -> str:
    return hashlib.sha256(normalize_title(title).encode("utf-8")).hexdigest()


def title_similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


# ---------- SimHash ----------

def _tokenize(text: str) -> list[str]:
    """中英混合粗分词：中文按 2-gram，英文/数字按单词。"""
    tokens = []
    for m in re.finditer(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", text):
        seg = m.group(0)
        if "\u4e00" <= seg[0] <= "\u9fff":
            if len(seg) == 1:
                tokens.append(seg)
            else:
                tokens.extend(seg[i:i + 2] for i in range(len(seg) - 1))
        else:
            tokens.append(seg.lower())
    return tokens or [text[:20]]


def simhash64(text: str) -> str:
    """64 位 SimHash，返回 16 位 hex（跨数据库一致）。"""
    tokens = _tokenize(text[:8000])
    v = [0] * 64
    for token in tokens:
        h = int.from_bytes(hashlib.md5(token.encode("utf-8")).digest()[:8], "big")
        for i in range(64):
            v[i] += 1 if (h >> (63 - i)) & 1 else -1
    fingerprint = 0
    for i, val in enumerate(v):
        if val > 0:
            fingerprint |= 1 << (63 - i)
    return f"{fingerprint:016x}"


def hamming_distance_hex(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")
