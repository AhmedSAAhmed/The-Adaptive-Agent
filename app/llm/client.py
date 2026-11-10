"""OpenAI-compatible LLM client with an ordered provider failover chain.

OpenRouter (Claude) -> Groq -> Gemini. Every call has a timeout, is parsed as strict JSON,
and is reported to an observer (persisted to `llm_calls`). If every provider fails, callers
fall back to the deterministic planner: the demo never depends on one vendor being up.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from openai import AsyncOpenAI

from app.config import Provider, settings

log = logging.getLogger(__name__)


@dataclass
class LLMResult:
    data: dict[str, Any]
    provider: str
    model: str
    latency_ms: int


Observer = Callable[[dict[str, Any]], Awaitable[None] | None]


def parse_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in response")
    return json.loads(text[start : end + 1])


class LLMClient:
    def __init__(self, providers: list[Provider] | None = None, timeout_s: float | None = None) -> None:
        self.providers = providers if providers is not None else settings.providers
        self.timeout_s = timeout_s or settings.llm_timeout_s
        self._cooldown_until: dict[str, float] = {}  # circuit breaker: skip a provider that just failed hard
        self._clients = {
            p.name: AsyncOpenAI(base_url=p.base_url, api_key=p.api_key, timeout=self.timeout_s, max_retries=0)
            for p in self.providers
        }

    @property
    def available(self) -> bool:
        return settings.llm_enabled and bool(self.providers)

    async def complete_json(self, system: str, user: str, purpose: str, observer: Observer | None = None) -> LLMResult | None:
        if not self.available:
            return None
        for p in self.providers:
            if self._cooldown_until.get(p.name, 0) > time.time():
                await _emit(observer, {"provider": p.name, "model": p.model, "purpose": purpose, "ok": False,
                                       "latency_ms": 0, "error": "skipped: circuit open (recent 402/429/timeout)"})
                continue
            t0 = time.perf_counter()
            record: dict[str, Any] = {"provider": p.name, "model": p.model, "purpose": purpose}
            try:
                resp = await self._clients[p.name].chat.completions.create(
                    model=p.model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    temperature=0.2,
                    max_tokens=settings.llm_max_tokens,
                )
                content = resp.choices[0].message.content or ""
                data = parse_json(content)
                latency = int((time.perf_counter() - t0) * 1000)
                usage = getattr(resp, "usage", None)
                record.update(ok=True, latency_ms=latency,
                              tokens_in=getattr(usage, "prompt_tokens", None), tokens_out=getattr(usage, "completion_tokens", None))
                await _emit(observer, record)
                return LLMResult(data=data, provider=p.name, model=p.model, latency_ms=latency)
            except Exception as exc:  # noqa: BLE001 - any provider failure means "try the next one"
                latency = int((time.perf_counter() - t0) * 1000)
                record.update(ok=False, latency_ms=latency, error=f"{type(exc).__name__}: {str(exc)[:200]}")
                log.warning("LLM provider %s failed for %s: %s", p.name, purpose, record["error"])
                status = getattr(exc, "status_code", None)
                if status in (401, 402, 403, 429) or "Timeout" in type(exc).__name__:
                    self._cooldown_until[p.name] = time.time() + 60
                await _emit(observer, record)
        return None


async def _emit(observer: Observer | None, record: dict[str, Any]) -> None:
    if observer is None:
        return
    out = observer(record)
    if hasattr(out, "__await__"):
        await out  # type: ignore[misc]
