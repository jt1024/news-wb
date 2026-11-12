"""AI 解读流水线：批量解读 status=fetched 的新闻。"""
import json
import logging
import re
import time
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..db import SessionLocal
from ..models import News, Tag
from .client import AIQuotaError, AIRateLimitError, chat

log = logging.getLogger("ai.pipeline")

PROMPT_SYSTEM = (
    "你是中国政务政策分析专家。对给定的政务新闻输出严格 JSON，字段："
    'summary(一句话摘要，80字内)；'
    'key_points(3-5条核心要点，每条是一个可读的自然语言句子，40字内，'
    "把政策对象、关键措施、时间节点、涉及金额自然地写进句子里；"
    "禁止输出字典/JSON/花括号格式)；"
    'analysis(影响与政策信号解读，150字内，客观克制)；'
    'confidence(0到1的置信度)；'
    'tags(1-3个主题标签，从给定列表选择，也可自拟)；'
    'content_type(news|notice|policy|interpretation|procurement其一)。'
    "只输出 JSON，不要其他文字。"
)

ALLOWED_TAGS = ["经济", "科技", "民生", "教育", "医疗", "住房", "交通", "营商环境",
                "产业", "招采", "人事", "安全", "生态环保", "文旅", "农业", "其他"]

# 政策文件特征关键词：命中则用强模型精读
POLICY_KEYWORDS = re.compile(
    r"(政策|意见|通知|公告|办法|条例|规定|细则|方案|规划|措施|纲要|征求意见|印发|实施细则|管理办法|行动计划|实施方案|若干措施|白皮书)"
)

# 模型侧明确拒答（如 422 内容审核）属于确定性失败：重试多少次结果都一样。
# 若仍留在 status=fetched，每轮定时任务都会把这批文章重新捞出来，
# 白白耗掉配额和时间，还会让「本轮解读」永远跑不完。429/402 单独处理，不在此列。
PERMANENT_AI_ERROR_RE = re.compile(r"Client error '4(?!02|29)\d\d|HTTP 4(?!02|29)\d\d")


def is_permanent_ai_failure(err: str) -> bool:
    return bool(PERMANENT_AI_ERROR_RE.search(err or ""))


def is_policy_like(news: News) -> bool:
    """标题/URL 预判是否政策文件类，决定用强模型还是轻量模型。"""
    return bool(POLICY_KEYWORDS.search(news.title or ""))


def pick_model(news: News) -> str:
    return config.ai_strong_model() if is_policy_like(news) else config.ai_model()


def build_prompt(news: News) -> str:
    tags_hint = "、".join(ALLOWED_TAGS)
    # 外省省级新闻 region_city 为空，只写 city 会让来源变成「（，发布于…）」，
    # 也会让模型误按广东口径解读；按 市 > 省 > 全国 的顺序补全归属。
    place = news.region_city or news.region_province or "全国"
    return (
        f"标题：{news.title}\n"
        f"来源：{news.source.name}（{place}，发布于 {news.publish_time or '未知'}）\n"
        f"正文：\n{news.content_text[:4000]}\n\n"
        f"可选主题标签：{tags_hint}"
    )


def parse_llm_json(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("AI 返回空内容")
    # 推理模型（如 MiniMax-M3）会输出 <think>...</think> 思考块，先剥掉，
    # 避免思考内容里的花括号干扰 JSON 提取
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    # 从每个 { 起尝试解析，取第一个合法 JSON 对象。
    # 这样即使 <think> 未闭合、模型夹带解释文字，也能拿到真正的 JSON。
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", raw):
        try:
            obj, _ = decoder.raw_decode(raw[m.start():])
            if isinstance(obj, dict):
                return obj
        except ValueError:
            continue
    raise ValueError(f"AI 返回内容中未找到合法 JSON（前 80 字：{raw[:80]}）")


def interpret_one(db: Session, news: News, retries: int | None = None) -> bool:
    """解读单条新闻（带重试），成功返回 True，失败原因写入 ai_error。

    政策文件类自动使用强模型（AI_MODEL_STRONG），其余用轻量模型。
    """
    retries = config.INTERPRET_RETRIES if retries is None else retries
    model = pick_model(news)
    last_err = ""
    for attempt in range(retries + 1):
        meta: dict = {}
        try:
            raw = chat([
                {"role": "system", "content": PROMPT_SYSTEM},
                {"role": "user", "content": build_prompt(news)},
            ], model=model, meta=meta)
            data = parse_llm_json(raw)
        except AIQuotaError:
            # 额度耗尽时立刻中止整轮，避免把剩余新闻逐条标记失败、白耗请求；
            # 新闻保持 status=fetched，额度恢复后下一轮自动补解读
            news.ai_error = "AI 402：额度不足，本轮解读中止"
            raise
        except AIRateLimitError as e:
            last_err = str(e)[:500]
            wait = 3 * (2 ** attempt)  # 3s / 6s / 12s
            log.warning("interpret #%s rate limited, sleep %ss (attempt %d)", news.id, wait, attempt + 1)
            time.sleep(wait)
            continue
        except Exception as e:  # noqa: BLE001
            last_err = str(e)[:500]
            log.warning("interpret #%s attempt %d failed: %s", news.id, attempt + 1, last_err)
            continue
        # 若本次实际走的是备用通道，记录真实使用的模型名
        _apply_result(db, news, data, meta.get("model") or model)
        return True
    news.ai_error = last_err
    if is_permanent_ai_failure(last_err):
        # 标记为终态，run_interpret 的 status=fetched 查询不再捞它；
        # 需要重试时手动把 status 改回 fetched 即可（原文与抓取结果都保留）。
        news.status = "failed"
        log.warning("interpret #%s permanently rejected by model, marked failed", news.id)
    return False


def _apply_result(db: Session, news: News, data: dict, model: str = ""):
    news.ai_summary = str(data.get("summary", ""))[:500]
    kp = data.get("key_points", [])
    # 兼容模型偶尔输出 dict 的情况：转成可读句子
    points = []
    for x in (kp if isinstance(kp, list) else [])[:6]:
        if isinstance(x, dict):
            x = "；".join(f"{k}：{v}" for k, v in x.items())
        x = str(x).strip()
        if x:
            points.append(x[:120])
    news.ai_key_points = points
    news.ai_analysis = str(data.get("analysis", ""))[:2000]
    try:
        news.ai_confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        news.ai_confidence = 0.5
    news.ai_model = model or config.ai_model()
    news.ai_error = ""
    news.content_type = data.get("content_type", "news")
    if news.content_type not in ("news", "notice", "policy", "interpretation", "procurement"):
        news.content_type = "news"

    # 打标签
    for name in (data.get("tags") or [])[:3]:
        name = str(name).strip()[:40]
        if not name:
            continue
        tag = db.execute(select(Tag).where(Tag.name == name)).scalar_one_or_none()
        if not tag:
            tag = Tag(name=name, category="theme")
            db.add(tag)
            db.flush()
        if tag not in news.tags:
            news.tags.append(tag)

    news.status = "interpreted"
    news.review_status = "pending" if news.ai_confidence < 0.6 else "auto"
    news.interpreted_at = datetime.now()


def run_interpret(batch_size: int = 20, progress_cb=None) -> dict:
    """处理一批待解读新闻。batch_size 不传时使用配置默认值。"""
    batch_size = batch_size or config.INTERPRET_BATCH_SIZE
    db: Session = SessionLocal()
    try:
        pending = db.execute(
            select(News).where(News.status == "fetched").order_by(News.id).limit(batch_size)
        ).scalars().all()
        total = len(pending)
        ok = failed = 0
        for i, news in enumerate(pending):
            if progress_cb:
                progress_cb({"phase": "解读中", "done": i, "total": total,
                             "current": news.title[:24]})
            if interpret_one(db, news):
                ok += 1
            else:
                failed += 1
            db.commit()
        return {"processed": total, "ok": ok, "failed": failed}
    finally:
        db.close()
