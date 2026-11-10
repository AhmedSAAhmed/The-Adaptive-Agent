"""HTML renderers for the live side-by-side view. Pure functions of session state."""
from __future__ import annotations

import html
import json
from itertools import zip_longest
from typing import Any

from app.core.agent import Agent
from app.core.session import Session

LABELS = {
    "baseline": ("Baseline", "Static agent: executes the plan as written, never re-checks."),
    "naive": ("Naive adaptive", "Re-plans on every contradiction and trusts every signal. No guards."),
    "adaptive": ("Adaptive (guarded)", "Re-plans only when an assumption breaks, through confirmation, budget and pre-commit guards."),
}
ICON = {"pending": "·", "running": "▸", "waiting": "…", "done": "✓", "skipped": "↺", "failed": "✗", "blocked": "⛔"}
VERDICT = {"success": "Correct outcome", "silent_failure": "Silent failure", "failure": "Wrong outcome",
           "escalated": "Safely escalated", "degraded": "Degraded"}


def e(x: Any) -> str:
    return html.escape(str(x), quote=True)


def _short(v: Any) -> str:
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= 90 else s[:87] + "…"


def agent_panel(agent: Agent | None, mode: str) -> str:
    title, sub = LABELS[mode]
    if agent is None:
        return f'<div class="panel"><div class="eyebrow">/// {e(mode)}</div><h3>{e(title)}</h3><div class="sub">{e(sub)}</div><div class="empty">Waiting for the plan…</div></div>'
    live = agent.status in ("executing", "re-planning")
    badges = [f'<span class="badge {"live" if live else ""}">{e(agent.status)}</span>',
              f'<span class="badge">plan v{agent.plan.version}</span>',
              f'<span class="badge">{e(agent.plan.created_by)}</span>',
              f'<span class="badge">LLM calls: {agent.llm_calls}</span>']
    if agent.unhealthy_sources:
        badges.append(f'<span class="badge bad">unhealthy: {e(", ".join(sorted(agent.unhealthy_sources)))}</span>')
    rows = []
    for s in agent.plan.steps:
        tags = '<span class="tag irr">irreversible</span>' if s.irreversible else ""
        args = ", ".join(f"{k}={_short(v)}" for k, v in s.args.items() if not k.startswith(("message", "question")))
        rows.append(f'<li class="st-{s.status}"><span class="ico">{ICON.get(s.status, "·")}</span>'
                    f'<span><code>{e(s.tool)}</code> <span style="font-size:12px">{e(args)}</span>'
                    f'<span class="desc">{e(s.description)}</span></span>{tags}</li>')
    chat = []
    for m in agent.sim.outbox[-3:]:
        cls = "q" if m["kind"] == "question" else ""
        chat.append(f'<div class="bubble {cls}">{e(m["en"])}<div class="ar" dir="rtl">{e(m["ar"])}</div></div>')
    reply = agent.world.get("customer.reply")
    if reply:
        chat.append(f'<div class="bubble q" style="align-self:flex-end">Customer: {e(reply)}</div>')
    out = ""
    if agent.outcome:
        o = agent.outcome
        det = "".join(f"<li>{e(d)}</li>" for d in o["details"])
        met = "".join(f"<span>{e(k.replace('_', ' '))}: <b>{e(v)}</b></span>" for k, v in o["metrics"].items())
        out = (f'<div class="outcome v-{e(o["verdict"])}"><div class="verdict">{e(VERDICT.get(o["verdict"], o["verdict"]))}</div>'
               f'<strong>{e(o["headline"])}</strong>{"<ul>" + det + "</ul>" if det else ""}<div class="metrics">{met}</div>'
               f'<div class="metrics">Audited against the system of record, not the agent\'s own beliefs. '
               f'<a href="/api/runs/{e(agent.run_id)}/trace.md" target="_blank">trace.md</a></div></div>')
    return (f'<div class="panel"><div class="eyebrow">/// {e(mode)}</div><h3>{e(title)}</h3><div class="sub">{e(sub)}</div>'
            f'<div class="badges">{"".join(badges)}</div><ol class="steps">{"".join(rows)}</ol>'
            f'{out}<div class="chat"><div class="eyebrow" style="margin-top:8px">/// WhatsApp</div>{"".join(chat) or "<div class=empty>No messages yet.</div>"}</div></div>')


def revisions_panel(agent: Agent | None) -> str:
    if agent is None or not agent.revisions:
        return '<div class="empty">No revisions yet. The agent changes its mind only when an incoming signal breaks an assumption.</div>'
    items = []
    for r in agent.revisions:
        t = max(0.0, r.ts - agent.t0_wall)
        broken = "".join(f'<div class="meta">broke <code>{e(b.assumption.describe())}</code> on <code>{e(b.step_tool)}</code> '
                         f'(actual <code>{e(_short(b.actual))}</code>): {e(b.assumption.why)}</div>' for b in r.broken)
        arrow = f"plan v{r.from_version} → v{r.to_version}" if r.to_version != r.from_version else f"plan v{r.from_version} kept"
        items.append(f'<li><div class="t">+{t:4.1f}s</div><div><div class="d {e(r.decision)}">{e(r.decision)}</div>'
                     f'<div class="reason">{e(r.reason_en)}</div>'
                     f'{f"<div class=rtl dir=rtl>{e(r.reason_ar)}</div>" if r.reason_ar else ""}'
                     f'<div class="meta">trigger: <code>{e(r.trigger)}</code> · {e(arrow)} · decided by <code>{e(r.planner)}</code></div>{broken}</div></li>')
    return f'<ol class="timeline">{"".join(reversed(items))}</ol>'


def events_panel(session: Session | None) -> str:
    if session is None or not session.agents:
        return '<div class="empty">The event stream appears here: webhooks, branch feeds, courier signals.</div>'
    modes = list(session.agents)
    lists = [[ev for ev in session.agents[m].events if ev.key != "customer.reply"] for m in modes]
    ref = session.agents[modes[-1]]
    rows = []
    for pair in zip_longest(*lists):
        ev = next(x for x in pair if x is not None)
        t = max(0.0, ev.ts - ref.t0_wall)
        cells = "".join(f'<td><span class="h {e(x.handled_as)}">{e(x.handled_as)}</span></td>' if x else "<td></td>" for x in pair)
        rows.append(f'<tr><td>+{t:4.1f}s</td><td>{e(ev.source)}</td><td><code>{e(ev.key)}</code> = <b>{e(_short(ev.value))}</b>'
                    f'<div style="color:var(--muted);font-size:12px">{e(ev.note)}</div></td><td>{e(ev.trust)}</td>{cells}</tr>')
    head = "".join(f"<th>{e(LABELS[m][0])}</th>" for m in modes)
    body = "".join(reversed(rows)) or '<tr><td colspan="6" class="empty">No events yet.</td></tr>'
    return f'<table class="ev"><thead><tr><th>t</th><th>source</th><th>signal</th><th>trust</th>{head}</tr></thead><tbody>{body}</tbody></table>'


def status_line(session: Session | None) -> str:
    if session is None:
        return "Pick a scenario and press **Run side by side**."
    if session.status == "planning":
        return "Planning: the LLM is drafting the initial plan (both agents get the same plan)…"
    if session.status == "running":
        return f"Running · session `{session.id}` · inject your own event below to break the plan live."
    return f"Finished · session `{session.id}` · every event, plan version and revision is stored in the database."


def history_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty">No runs stored yet.</div>'
    out = []
    for s in rows:
        runs = " ".join(
            f'<a href="/api/runs/{e(r["id"])}/trace.md" target="_blank">{e(r["mode"])}</a>: '
            f'<span class="h">{e((r.get("outcome") or {}).get("verdict", r["status"]))}</span>' for r in s["runs"])
        out.append(f'<tr><td><code>{e(s["id"])}</code></td><td>{e(s["scenario"])}</td><td>{e(s["status"])}</td><td>{runs}</td></tr>')
    return f'<table class="ev"><thead><tr><th>session</th><th>scenario</th><th>status</th><th>runs (trace)</th></tr></thead><tbody>{"".join(out)}</tbody></table>'
