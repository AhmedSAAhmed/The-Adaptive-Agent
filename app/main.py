"""FastAPI app: JSON/SSE API + webhook for streaming events, with the Gradio UI mounted at /."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque
from typing import Any, Literal

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import gradio as gr  # noqa: E402
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.core.models import Event
from app.core.session import Session, SessionManager
from app.scenarios import SCENARIOS
from app.store.db import Store, trace_markdown
from app.ui.app import build_ui
from app.ui.theme import CSS, HEAD, JS, navy_theme

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("adaptive-agent")


class EventIn(BaseModel):
    key: str = Field(min_length=3, max_length=120)
    value: Any
    source: str = Field(default="webhook", max_length=60)
    trust: Literal["high", "low"] = "high"
    session_id: str | None = None
    note: str = Field(default="", max_length=300)


class SessionIn(BaseModel):
    scenario: Literal["A", "B", "C"]


class RateLimiter:
    """Small in-memory sliding-window limiter for write endpoints (one instance, free tier)."""

    def __init__(self, limit: int, window_s: float) -> None:
        self.limit, self.window_s = limit, window_s
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, who: str) -> None:
        now, q = time.time(), self.hits[who]
        while q and now - q[0] > self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            raise HTTPException(429, "rate limit exceeded, slow down")
        q.append(now)


def session_state(s: Session) -> dict[str, Any]:
    return {
        "id": s.id, "scenario": s.scenario.id, "status": s.status, "version": s.version,
        "agents": {
            mode: {
                "run_id": a.run_id, "status": a.status, "plan_version": a.plan.version, "planner": a.plan.created_by,
                "steps": [{"tool": st.tool, "status": st.status, "irreversible": st.irreversible} for st in a.plan.steps],
                "revisions": [{"decision": r.decision, "reason_en": r.reason_en, "reason_ar": r.reason_ar, "trigger": r.trigger}
                              for r in a.revisions],
                "events": [{"source": ev.source, "key": ev.key, "value": ev.value, "trust": ev.trust, "handled_as": ev.handled_as}
                           for ev in a.events],
                "outcome": a.outcome,
            }
            for mode, a in s.agents.items()
        },
    }


def create_app() -> FastAPI:
    store = Store()
    manager = SessionManager(store)
    writes = RateLimiter(limit=30, window_s=60)
    app = FastAPI(title="The Adaptive Agent", version="1.0.0",
                  description="Plan -> execute -> observe -> re-evaluate, with a streaming event webhook.")
    log.info("storage=%s llm_chain=%s", store.backend, [f"{p.name}:{p.model}" for p in settings.providers] or "deterministic")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "storage": store.backend, "llm_providers": [p.name for p in settings.providers],
                "running_sessions": len(manager.running())}

    @app.get("/api/scenarios")
    async def scenarios() -> list[dict[str, Any]]:
        return [{"id": s.id, "name": s.name, "tagline": s.tagline, "modes": list(s.modes)} for s in SCENARIOS.values()]

    @app.post("/api/sessions")
    async def start_session(body: SessionIn, request: Request) -> dict[str, Any]:
        writes.check(request.client.host if request.client else "?")
        try:
            s = manager.start(body.scenario)
        except RuntimeError as exc:
            raise HTTPException(429, str(exc)) from exc
        return {"session_id": s.id, "stream": f"/api/sessions/{s.id}/stream"}

    @app.get("/api/sessions")
    async def list_sessions(limit: int = 20) -> list[dict[str, Any]]:
        return await asyncio.to_thread(store.recent_sessions, min(limit, 100))

    @app.get("/api/sessions/{sid}")
    async def get_session(sid: str) -> dict[str, Any]:
        s = manager.sessions.get(sid)
        if not s:
            raise HTTPException(404, "session not live on this instance (see /api/sessions for stored history)")
        return session_state(s)

    @app.get("/api/sessions/{sid}/stream")
    async def stream(sid: str) -> StreamingResponse:
        s = manager.sessions.get(sid)
        if not s:
            raise HTTPException(404, "session not found")

        async def gen():  # pushes a snapshot on every state change (event-driven, no fixed polling)
            q = s.subscribe()
            try:
                yield f"data: {json.dumps(session_state(s), ensure_ascii=False, default=str)}\n\n"
                while not s.finished:
                    try:
                        await asyncio.wait_for(q.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    while not q.empty():
                        q.get_nowait()
                    yield f"data: {json.dumps(session_state(s), ensure_ascii=False, default=str)}\n\n"
                yield f"event: end\ndata: {json.dumps(session_state(s), ensure_ascii=False, default=str)}\n\n"
            finally:
                s.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/api/events")
    async def push_event(body: EventIn, request: Request, x_webhook_token: str | None = Header(default=None)) -> dict[str, Any]:
        if settings.webhook_token and x_webhook_token != settings.webhook_token:
            raise HTTPException(401, "invalid webhook token")
        writes.check(request.client.host if request.client else "?")
        s = manager.sessions.get(body.session_id) if body.session_id else manager.latest_running()
        if s is None or s.finished:
            raise HTTPException(409, "no run in progress: start a scenario first (UI or POST /api/sessions)")
        ev = Event(source=body.source, key=body.key, value=body.value, trust=body.trust, note=body.note or "webhook")
        n = await s.inject(ev)
        return {"delivered_to": n, "session_id": s.id, "event_id": ev.id}

    @app.get("/api/runs/{rid}/trace.md", response_class=PlainTextResponse)
    async def trace(rid: str) -> str:
        return trace_markdown(await asyncio.to_thread(store.run_trace, rid))

    blocks = build_ui(manager, store)
    return gr.mount_gradio_app(app, blocks, path="/", theme=navy_theme(), css=CSS, head=HEAD, js=JS, ssr_mode=False,
                               footer_links=["api"])


app = create_app()
