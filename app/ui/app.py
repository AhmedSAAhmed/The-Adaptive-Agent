"""Gradio UI: scripted scenarios, "Try it yourself", revision trace, live event injection and customer chat."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

import gradio as gr

from app.config import settings
from app.core.models import Event
from app.core.ratelimit import RateLimited, custom_runs
from app.core.session import Session, SessionManager
from app.scenarios import BRANCHES, SCENARIOS, Scenario
from app.scenarios.custom import MAX_CHARS, build_custom, parse_request
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
  <div><div class="eyebrow">03</div><h4>Observe</h4><p>Webhooks, feeds and customer replies stream into an async event bus. The monitor re-checks only the assumptions that depend on the key that changed.</p></div>
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

- `POST /api/sessions` with `{{"request": "cancel order 5521 and refund me", "twist": "auto"}}` runs your own request.
- `POST /api/sessions/{{id}}/reply` with `{{"text": "No, make it 21:30"}}` answers as the customer.
- `trust: "low"` events are confirmed against the system of record before they can change anything.
- `GET /api/sessions/{{id}}/stream` streams live state as Server-Sent Events.
- `GET /api/runs/{{run_id}}/trace.md` exports a full plain-text trace of a run.
"""

KEYS = {
    "A": ["order.ORD-7781.status"],
    "B": ["branch.olaya.open_until", "branch.king_fahd.open_until", "branch.king_fahd.slot.20:00"],
    "C": ["order.ORD-9902.status"],
}

EXAMPLES = [
    "Hi, I'm Lina. Please cancel order 5521 and refund me, it was SAR 230",
    "السلام عليكم معك فهد، أبغى ألغي طلبي رقم ٤٤١٢ وأسترجع فلوسي",
    "Book a table for 4 at 9pm at King Fahd Road please, it's a birthday",
    "أبغى أحجز طاولة لـ 8 أشخاص الساعة 8 الليلة في فرع الملقا",
]
TWISTS = [
    ("Auto: the most likely real-world change", "auto"),
    ("Flapping low-trust signal (failure test)", "flapping"),
    ("Nothing: I'll break it myself", "none"),
]


def keys_for(sc: Scenario) -> list[str]:
    if sc.id in KEYS:
        return KEYS[sc.id]
    c = sc.mission.customer
    if sc.mission.kind == "refund":
        return [f"order.{c['order_id']}.status"]
    b, t = c["branch"], c["time"]
    return [f"branch.{b}.open_until", f"branch.{b}.slot.{t}"] + [f"branch.{a}.open_until" for a in c["alternatives"]]


def story_html(sc: Scenario) -> str:
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


def live_view(prefix: str) -> dict[str, Any]:
    """The side-by-side block, reused by both tabs."""
    c: dict[str, Any] = {}
    c["status"] = gr.Markdown(render.status_line(None))
    with gr.Row(equal_height=True):
        c["left"] = gr.HTML(render.agent_panel(None, "baseline"))
        c["right"] = gr.HTML(render.agent_panel(None, "adaptive"))
    c["chat_row"] = gr.Row(visible=prefix == "try")
    with c["chat_row"]:
        c["chat"] = gr.Textbox(label="Reply as the customer (WhatsApp)", placeholder="e.g. No, King Fahd is too far, make it 21:30 at Olaya · أو: نعم أكد الحجز",
                               scale=4, max_length=300)
        c["chat_btn"] = gr.Button("Send reply", scale=1)
    c["chat_out"] = gr.Markdown(visible=prefix == "try")
    gr.HTML('<div class="eyebrow" style="margin-top:24px">/// I changed my mind because…</div>')
    c["revisions"] = gr.HTML(render.revisions_panel(None))
    gr.HTML('<div class="eyebrow" style="margin-top:24px">/// Event stream (streamed, not polled)</div>')
    c["events"] = gr.HTML(render.events_panel(None))
    with gr.Accordion("Inject a real-world event while a run is in progress", open=False):
        with gr.Row():
            c["key"] = gr.Dropdown(choices=KEYS["A"], value=KEYS["A"][0], allow_custom_value=True, label="key")
            c["value"] = gr.Textbox(value="picked_up", label="value (JSON or text)")
            c["source"] = gr.Textbox(value="order_system", label="source")
            c["trust"] = gr.Radio(choices=["high", "low"], value="high", label="trust")
        c["inject_btn"] = gr.Button("Send event")
        c["inject_out"] = gr.Markdown()
    return c


def build_ui(manager: SessionManager, store: Store) -> gr.Blocks:
    choices = [(s.name, s.id) for s in SCENARIOS.values()]

    async def stream(s: Session) -> AsyncIterator[tuple[Any, ...]]:
        keys = keys_for(s.scenario)
        first = True
        while True:
            yield (*frame(s), s.id, gr.update(choices=keys, value=keys[0]) if first else gr.update())
            first = False
            if s.finished:
                break
            await s.wait_change(timeout=1.0)
        yield (*frame(s), s.id, gr.update())

    async def run_scripted(sid: str) -> AsyncIterator[tuple[Any, ...]]:
        try:
            s = manager.start(sid)
        except RuntimeError as exc:
            raise gr.Error(str(exc))
        async for out in stream(s):
            yield out

    async def run_custom(text: str, twist: str, human: bool, request: gr.Request) -> AsyncIterator[tuple[Any, ...]]:
        text = (text or "").strip()
        if not text:
            raise gr.Error("Write a request first, or pick one of the examples.")
        try:
            custom_runs.check(getattr(getattr(request, "client", None), "host", None) or "?")
        except RateLimited as exc:
            raise gr.Error(str(exc))
        records: list[dict[str, Any]] = []
        yield (gr.update(), gr.update(), gr.update(), gr.update(), "Understanding your request…", "", gr.update(),
               '<div class="story"><div class="eyebrow">/// Understanding</div>Reading your message…</div>', gr.update())
        req = await parse_request(text, manager.planner.llm, records.append)
        if req.kind == "out_of_scope":
            msg = ('<div class="story"><div class="eyebrow">/// Out of scope for this demo</div>'
                   "This demo agent can <b>cancel and refund a food order</b> or <b>book a table</b>. Try one of the examples."
                   '<div class="rtl" dir="rtl">يمكن لهذا الوكيل التجريبي إلغاء طلب واسترداد المبلغ، أو حجز طاولة. جرّب أحد الأمثلة.</div></div>')
            yield (gr.update(), gr.update(), gr.update(), gr.update(), "Nothing started.", "", gr.update(), msg, gr.update())
            return
        sc = build_custom(req, text, twist, human)  # type: ignore[arg-type]
        try:
            s = manager.start_scenario(sc, llm_records=records)
        except RuntimeError as exc:
            raise gr.Error(str(exc))
        card = understood_card(req, sc, human)
        async for out in stream(s):
            yield (*out, card, gr.update(visible=human))

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

    async def reply(session_id: str, text: str) -> tuple[str, str]:
        s = manager.sessions.get(session_id)
        if s is None or s.finished:
            return "No run in progress.", text
        if not text.strip():
            return "Type a reply first.", text
        n = await s.reply(text.strip())
        return f"Sent to {n} agent(s): “{text.strip()}”", ""

    with gr.Blocks(title="The Adaptive Agent · DOO", analytics_enabled=False) as demo:
        gr.HTML(HERO)
        with gr.Tab("Live demo"):
            sid_a = gr.State("")
            with gr.Row(equal_height=False):
                with gr.Column(scale=2):
                    scenario = gr.Radio(choices=choices, value="A", label="Scenario")
                with gr.Column(scale=1, min_width=220):
                    run_btn = gr.Button("Run side by side", variant="primary", size="lg")
            story = gr.HTML(story_html(SCENARIOS["A"]))
            va = live_view("demo")

        with gr.Tab("Try it yourself"):
            sid_b = gr.State("")
            gr.HTML('<div class="eyebrow" style="margin-top:8px">/// Your own case</div>'
                    '<h2 style="font-weight:600;margin:0 0 8px">Write it like a customer on <em>WhatsApp</em></h2>'
                    '<p style="color:var(--muted);margin:0 0 12px">English or Arabic. The agent supports two jobs: cancel and refund a '
                    'food order, or book a table (branches: Olaya, King Fahd Road, Al Malqa). Pick how reality changes, then answer '
                    'the agents yourself when they ask you something. Say “no” and watch who listens.</p>')
            with gr.Row(equal_height=False):
                with gr.Column(scale=3):
                    req_text = gr.Textbox(label="Customer message", lines=2, max_length=MAX_CHARS,
                                          placeholder="e.g. Book a table for 4 at 9pm at King Fahd Road · أو: أبغى ألغي طلبي رقم 4412")
                    gr.Examples(EXAMPLES, inputs=req_text, label="Examples")
                with gr.Column(scale=2, min_width=260):
                    twist = gr.Radio(choices=TWISTS, value="auto", label="How reality changes mid-plan")
                    human = gr.Checkbox(value=True, label="I'll reply as the customer (otherwise a simulated customer says yes)")
                    try_btn = gr.Button("Run my request side by side", variant="primary", size="lg")
            understood = gr.HTML('<div class="empty">The agent will show what it understood before it starts.</div>')
            vb = live_view("try")

        with gr.Tab("Architecture"):
            gr.HTML(ARCH)
            gr.Markdown(API_DOC.format(base="https://<your-render-url>"))
        with gr.Tab("Run history"):
            hist_btn = gr.Button("Refresh")
            hist = gr.HTML()
            gr.Markdown(f"Storage backend: `{store.backend}` · LLM chain: "
                        + (", ".join(f"`{p.name}:{p.model}`" for p in settings.providers) or "`deterministic only`"))

        def outs(v: dict[str, Any], sid: gr.State) -> list[Any]:
            return [v["left"], v["right"], v["revisions"], v["events"], v["status"], sid, v["key"]]

        scenario.change(lambda x: story_html(SCENARIOS[x]), scenario, story)
        run_btn.click(run_scripted, scenario, outs(va, sid_a), concurrency_limit=8)
        try_btn.click(run_custom, [req_text, twist, human], outs(vb, sid_b) + [understood, vb["chat_row"]], concurrency_limit=8)
        for v, sid in ((va, sid_a), (vb, sid_b)):
            v["inject_btn"].click(inject, [sid, v["key"], v["value"], v["source"], v["trust"]], v["inject_out"], concurrency_limit=16)
        vb["chat_btn"].click(reply, [sid_b, vb["chat"]], [vb["chat_out"], vb["chat"]], concurrency_limit=16)
        vb["chat"].submit(reply, [sid_b, vb["chat"]], [vb["chat_out"], vb["chat"]], concurrency_limit=16)
        hist_btn.click(lambda: render.history_table(store.recent_sessions()), None, hist)
        demo.load(lambda: render.history_table(store.recent_sessions()), None, hist)
    return demo


def understood_card(req: Any, sc: Scenario, human: bool) -> str:
    e = render.e
    if req.kind == "refund":
        rows = [("Intent", "Cancel and refund an order"), ("Order", f"{req.order_id} · SAR {req.order_total:.0f}"),
                ("Items", ", ".join(req.items))]
    else:
        rows = [("Intent", "Book a table"), ("Branch", f"{BRANCHES[req.branch][0]} ({BRANCHES[req.branch][1]})"),
                ("Time", req.time), ("Party", str(req.party_size))]
    rows += [("Customer", f"{req.name_en} · {req.name_ar}"), ("Language", "Arabic" if req.language == "ar" else "English"),
             ("Parsed by", req.parsed_by), ("You reply as customer", "yes" if human else "no (simulated)")]
    body = "".join(f"<tr><td style='color:var(--muted);width:180px'>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in rows)
    notes = "".join(f"<li>{e(n)}</li>" for n in req.notes)
    return (f'<div class="story"><div class="eyebrow">/// What the agent understood</div><table class="ev">{body}</table>'
            f'{"<ul style=margin-top:8px>" + notes + "</ul>" if notes else ""}'
            f'<div style="margin-top:10px">{_md(sc.story)}</div></div>')


def _md(text: str) -> str:
    """Tiny markdown: **bold** and `code` only (stories are generated by our code, values are escaped)."""
    import html
    import re

    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", t)
