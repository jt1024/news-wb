"""AI 客户端：DeepSeek / MiniMax / 千问（OpenAI 兼容接口统一适配）。"""
import json
import logging

import httpx

from .. import config

log = logging.getLogger("ai")


class AIRateLimitError(RuntimeError):
    """429：请求过于频繁，稍等后重试即可。"""


class AIQuotaError(RuntimeError):
    """402：额度/余额不足，重试无意义，应立即停止本轮解读。"""


def chat(messages: list[dict], temperature: float = 0.3, max_tokens: int = 4000, model: str = "") -> str:
    """调用 OpenAI 兼容 chat/completions，返回文本。model 可覆盖默认模型。

    推理模型（MiniMax-M3 等）的思考过程会占用输出 token，默认 4000 留足余量。
    """
    if not config.ai_enabled():
        raise RuntimeError("AI 未配置：请在 .env 中设置 AI_PROVIDER 与 AI_API_KEY")
    resp = httpx.post(
        f"{config.ai_base_url()}/chat/completions",
        headers={"Authorization": f"Bearer {config.AI_API_KEY}"},
        json={
            "model": model or config.ai_model(),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=120,
    )
    if resp.status_code == 402:
        raise AIQuotaError("MiniMax 返回 402：额度/余额不足，请充值或更换 API key")
    if resp.status_code == 429:
        raise AIRateLimitError("MiniMax 返回 429：请求过于频繁")
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"].get("content") or ""
    if not content.strip():
        raise ValueError("AI 返回空内容（可能被 max_tokens 截断）")
    return content
