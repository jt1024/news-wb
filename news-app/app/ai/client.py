"""AI 客户端：DeepSeek / MiniMax / 千问（OpenAI 兼容接口统一适配）。

主通道额度耗尽（402）时，若配置了备用通道会自动重放本次请求并继续解读；
未配置则原样抛出 AIQuotaError，由调度器负责中止本轮解读并推送告警。
"""
import logging

import httpx

from .. import config

log = logging.getLogger("ai")


class AIRateLimitError(RuntimeError):
    """429：请求过于频繁，稍等后重试即可。"""


class AIQuotaError(RuntimeError):
    """402：额度/余额不足，重试无意义，应立即停止本轮解读。"""


def _post_chat(base_url: str, api_key: str, model: str, messages: list[dict],
               temperature: float, max_tokens: int) -> str:
    resp = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=120,
    )
    if resp.status_code == 402:
        raise AIQuotaError(f"{base_url} 返回 402：额度/余额不足，请充值或更换 API key")
    if resp.status_code == 429:
        raise AIRateLimitError("AI 返回 429：请求过于频繁")
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"].get("content") or ""
    if not content.strip():
        raise ValueError("AI 返回空内容（可能被 max_tokens 截断）")
    return content


def chat(messages: list[dict], temperature: float = 0.3, max_tokens: int = 4000,
         model: str = "", meta: dict | None = None) -> str:
    """调用 OpenAI 兼容 chat/completions，返回文本。

    推理模型（MiniMax-M3 等）的思考过程会占用输出 token，默认 4000 留足余量。
    meta 若传入，会写入本次实际使用的模型名，供调用方记录到 news.ai_model。
    """
    if not config.ai_enabled():
        raise RuntimeError("AI 未配置：请在 .env 中设置 AI_PROVIDER 与 AI_API_KEY")

    primary_model = model or config.ai_model()
    if meta is not None:
        meta["model"] = primary_model
    try:
        return _post_chat(config.ai_base_url(), config.AI_API_KEY, primary_model,
                          messages, temperature, max_tokens)
    except AIQuotaError:
        if not config.ai_fallback_enabled():
            raise
        fallback_model = config.ai_fallback_model()
        log.warning("AI 主通道额度耗尽，自动切换备用通道 %s / %s",
                    config.AI_FALLBACK_PROVIDER, fallback_model)
        content = _post_chat(config.ai_fallback_base_url(), config.AI_FALLBACK_API_KEY,
                             fallback_model, messages, temperature, max_tokens)
        if meta is not None:
            meta["model"] = fallback_model
        return content
