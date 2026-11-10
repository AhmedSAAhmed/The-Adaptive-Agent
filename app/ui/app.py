"""Gradio UI: scenario picker, side-by-side runs, revision trace, live event injection."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

import gradio as gr

from app.config import settings
from app.core.models import Event
from app.core.session import Session, SessionManager
from app.scenarios import SCENARIOS
from app.store.db import Store
from app.ui import render

HERO = """
<div class="hero">
  <div class="eyebrow">/// The Adaptive Agent · built for DOO</div>
  <h1>Know your plan is <em>wrong</em> before your customer does</h1>
  <p>A customer-service action agent that runs a multi-step plan, watches a live event stream, and re-plans only when a
  signal breaks one of its assumptions. Every change of mind is explained, guarded and stored.</p>
  <div class="kpis">
    <div><b>0</b><span>timers or polling loops in the agent</span></div>
    <div><b>5</b><span>guards between a signal and an irreversible action</span></div>
    <div><b>3</b><span>LLM providers in failover, plus a deterministic planner</span></div>
    <div><b>EN · AR</b><span>every customer message, both languages</span></div>
  </div>
</div>
"""

ARCH = """
<div class="eyebrow">/// Architecture</div>
<h2 style="font-weight:600;margin:0 0 16px">From a broken assumption to a <em>safe</em> new plan</h2>
<div class="loop">
  <div><div class="eyebrow">01</div><h4>Plan</h4><p>The LLM drafts tool calls. Code rebuilds every step from the tool registry and attaches each tool's contract (e.g. refund requires <code>status in [placed, preparing]</code>).</p></div>
  <div><div class="eyebrow">02</div><h4>Execute</h4><p>Steps run against the business systems. Before any irreversible step, its contract is re-read from the system of record.</p></div>
  <div><div class="eyebrow">03</div><h4>Observe</h4><p>Webhooks and feeds stream into an async event bus. The monitor re-checks only the assumptions that depend on the key that changed.</p></div>
  <div><div class="eyebrow">04</div><h4>Re-evaluate</h4><p>Broken assumption → guards (confirm low-trust signals, flap detection, revision budget) → re-plan, ignore, or escalate to a human.</p></div>
</div>
<p style="color:var(--muted);margin-top:16px">Everything is event-sourced in Postgres (SQLite locally): events, plan versions, revisions, step transitions and LLM calls.
Source and docs: <a href="https://github.com/AhmedSAAhmed/The-Adaptive-Agent" target="_blank">github.com/AhmedSAAhmed/The-Adaptive-Agent</a>.</p>
"""

API_DOC = """
### Break a plan from your own terminal

While a run is in progress, any system can push an event. The agent reacts only if the event contradicts an assumption.

```bash
curl -X POST {base}/api/events -H "Content-Type: application/json" \\
  -d '{{"key": "order.ORD-7781.status", "value": "picked_up", "source": "order_system", "trust": "high"}}'
```

- `trust: "low"` events are confirmed against the system of record before they can change anything.
- `GET /api/sessions/{{id}}/stream` streams live state as Server-Sent Events.
- `GET /api/runs/{{run_id}}/trace.md` exports a full plain-text trace of a run.
- `GET /api/sessions` lists stored sessions with audited outcomes.
"""

KEYS = {
    "A": ["order.ORD-7781.status"],
    "B": ["branch.olaya.open_until", "branch.king_fahd.open_until", "branch.king_fahd.slot.20:00"],
    "C": ["order.ORD-9902.status"],
}


def build_ui(manager: SessionManager, store: Store) -> gr.Blocks:
    choices = [(s.name, s.id) for s in SCENARIOS.values()]

    def story(sid: str) -> str:
        sc = SCENARIOS[sid]
        left, right = (render.LABELS[m][0] for m in sc.modes)
        return (f'<div class="story"><div class="eyebrow">/// {render.e(sc.tagline)}</div>'
                f'{_md(sc.story)}<div style="margin-top:8px;color:var(--muted);font-size:13px">Comparison: <b>{left}</b> vs <b>{right}</b> · '
                f'same plan, same tools, same event stream.</div></div>')

    def frame(s: Session | None) -> tuple[str, str, str, str, str]:
        sc = s.scenario if s else None
        left_mode, right_mode = sc.modes if sc else ("baseline", "adaptive")
        left = render.agent_panel(s.agents.get(left_mode) if s else None, left_mode)
        right = render.agent_panel(s.agents.get(right_mode) if s else None, right_mode)
        revs = render.revisions_panel(s.agents.get(right_mode) if s else None)
        if s and left_mode == "naive":
            revs = ('<div class="eyebrow">/// guarded agent</div>' + revs +
                    '<div class="eyebrow" style="margin-top:20px">/// naive agent (thrashing)</div>' + render.revisions_panel(s.agents.get("naive")))
        return left, right, revs, render.events_panel(s), render.status_line(s)

    async def run(sid: str) -> AsyncIterator[tuple[Any, ...]]:
        try:
            s = manager.start(sid)
        except RuntimeError as exc:
            raise gr.Error(str(exc))
        while True:
            yield (*frame(s), s.id, gr.update(choices=KEYS[sid], value=KEYS[sid][0]))
            if s.finished:
                break
            await s.wait_change(timeout=1.0)
        yield (*frame(s), s.id, gr.update())

    async def inject(session_id: str, key: str, value: str, source: str, trust: str) -> str:
        s = manager.sessions.get(session_id) if session_id else manager.latest_running()
        if s is None or s.finished:
            return "No run in progress. Start a scenario first, then inject while it runs."
        try:
            parsed: Any = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            parsed = value
        n = await s.inject(Event(source=source or "ui", key=key.strip(), value=parsed, trust=trust, note="Injected from the UI"))  # type: ignore[arg-type]
        return f"Delivered `{key} = {parsed!r}` ({trust} trust) to {n} running agent(s)."

    with gr.Blocks(title="The Adaptive Agent · DOO", analytics_enabled=False) as demo:
        gr.HTML(HERO)
        session_id = gr.State("")
        with gr.Tab("Live demo"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=2):
                    scenario = gr.Radio(choices=choices, value="A", label="Scenario")
                with gr.Column(scale=1, min_width=220):
                    run_btn = gr.Button("Run side by side", variant="primary", size="lg")
            story_html = gr.HTML(story("A"))
            status = gr.Markdown(render.status_line(None))
            with gr.Row(equal_height=True):
                left = gr.HTML(render.agent_panel(None, "baseline"))
                right = gr.HTML(render.agent_panel(None, "adaptive"))
            gr.HTML('<div class="eyebrow" style="margin-top:24px">/// I changed my mind because…</div>')
            revisions = gr.HTML(render.revisions_panel(None))
            gr.HTML('<div class="eyebrow" style="margin-top:24px">/// Event stream (streamed, not polled)</div>')
            events = gr.HTML(render.events_panel(None))
            with gr.Accordion("Inject a real-world event while a run is in progress", open=False):
                with gr.Row():
                    key = gr.Dropdown(choices=KEYS["A"], value=KEYS["A"][0], allow_custom_value=True, label="key")
                    value = gr.Textbox(value="picked_up", label="value (JSON or text)")
                    source = gr.Textbox(value="order_system", label="source")
                    trust = gr.Radio(choices=["high", "low"], value="high", label="trust")
                inject_btn = gr.Button("Send event")
                inject_out = gr.Markdown()
        with gr.Tab("Architecture"):
            gr.HTML(ARCH)
            gr.Markdown(API_DOC.format(base="https://<your-render-url>"))
        with gr.Tab("Run history"):
            hist_btn = gr.Button("Refresh")
            hist = gr.HTML()
            gr.Markdown(f"Storage backend: `{store.backend}` · LLM chain: "
                        + (", ".join(f"`{p.name}:{p.model}`" for p in settings.providers) or "`deterministic only`"))

        scenario.change(story, scenario, story_html)
        run_btn.click(run, scenario, [left, right, revisions, events, status, session_id, key], concurrency_limit=8)
        inject_btn.click(inject, [session_id, key, value, source, trust], inject_out, concurrency_limit=16)
        hist_btn.click(lambda: render.history_table(store.recent_sessions()), None, hist)
        demo.load(lambda: render.history_table(store.recent_sessions()), None, hist)
    return demo


def _md(text: str) -> str:
    """Tiny markdown: **bold** and `code` only (scenario stories are authored by us)."""
    import html
    import re

    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", t)
