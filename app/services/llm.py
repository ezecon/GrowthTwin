"""Grok (xAI, OpenAI-compatible) client. Returns None on any failure so callers can fall back."""
import logging

import httpx

from ..core.config import get_settings

log = logging.getLogger("growthtwin.llm")


def available() -> bool:
    return bool(get_settings().xai_api_key)


async def chat(messages: list[dict], max_tokens: int = 900, temperature: float = 0.2) -> str | None:
    s = get_settings()
    if not s.xai_api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=s.llm_timeout_s) as client:
            r = await client.post(
                f"{s.xai_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {s.xai_api_key}"},
                json={"model": s.grok_model, "messages": messages,
                      "max_tokens": max_tokens, "temperature": temperature},
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:  # network, quota, bad payload...
        log.warning("LLM call failed: %s", e)
        return None
