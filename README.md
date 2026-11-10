# The Adaptive Agent

**Can an AI system recognise that reality changed, and safely change its mind?**

A customer-service *action* agent in the style of [DOO](https://www.doo.ooo) (WhatsApp refunds and bookings for GCC brands). It runs a multi-step plan, watches a live event stream, and re-plans **only when a signal breaks one of its assumptions**. Every revision is explained ("I changed my mind because…", in English and Arabic), guarded, and stored.

- **Live demo:** _add your Render URL here_ (free tier: allow ~1 min for a cold start)
- **Walkthrough video:** _add link_
- **Docs:** [Architecture](docs/ARCHITECTURE.md) · [Failure test](docs/FAILURE_TEST.md) · [Thesis](docs/THESIS.md) · [Notes for judges](docs/NOTES.md)

## What you will see

| Scenario | Reality changes mid-plan | Static plan | Adaptive agent |
|---|---|---|---|
| **A · Refund after dispatch** | Signed webhook: the courier picked up the order | Refunds SAR 186 for food that still arrives (reports success) | `cancel_order` contract breaks → voucher + live ETA |
| **B · Branch closes early** | Branch ops: Olaya closes at 21:00 tonight | Confirms a table for 6 that will be turned away | Releases the hold, moves to King Fahd Road, asks first, then confirms |
| **C · Flapping signal** (failure test) | Faulty courier webhook flips the status every ~0.8 s | *Naive* adaptive agent believes it and thrashes | *Guarded* agent confirms with the system of record, flags the source, refunds correctly |

Both columns get the same plan, tools and events. Outcomes are audited against the system of record, not the agent's beliefs.

## How it works

```
plan ──► execute ──► observe ──► re-evaluate
 ▲          │  pre-commit │  event bus  │  broken assumption?
 │          ▼  re-check   ▼  + guards   ▼
 └──── validated re-plan ◄── LLM proposes, code disposes ── or escalate to a human
```

- **Assumptions are typed predicates.** Tools carry code-owned contracts (e.g. refunds only for `status in [placed, preparing, cancelled]`). The monitor re-checks only assumptions on the key that changed. No timers, no polling, no re-prompting.
- **The LLM plans; code validates.** Groq (gpt-oss-120b) → OpenRouter (Claude Sonnet 5.5) → Gemini (3.5 Flash) → deterministic planner, with timeouts and a circuit breaker.
- **Five guards** between a signal and an irreversible action: confirm low-trust signals, flap detection, revision budget, pre-commit re-check, plan validation.
- **Event-sourced Postgres**: events, plan versions, revisions, steps and LLM calls. Every run exports a `trace.md`.

## Break it yourself

During a run (UI accordion, or from any terminal):

```bash
curl -X POST https://<your-app>.onrender.com/api/events -H "Content-Type: application/json" -d '{"key": "order.ORD-7781.status", "value": "picked_up", "source": "order_system", "trust": "high"}'
```

Other endpoints: `POST /api/sessions` `{"scenario":"A"}`, `GET /api/sessions/{id}/stream` (Server-Sent Events), `GET /api/runs/{id}/trace.md`, `GET /api/sessions`, `GET /health`.

## Run locally

```bash
git clone https://github.com/AhmedSAAhmed/The-Adaptive-Agent.git
```

```bash
cd The-Adaptive-Agent && pip install -r requirements.txt
```

```bash
cp .env.example .env
```

Add any of `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY` to `.env` (no quotes). With no keys it runs on the deterministic planner.

```bash
python -m uvicorn app.main:app --port 7860
```

Open http://localhost:7860. Storage defaults to SQLite in `./data`; set `DATABASE_URL` for Postgres.

Tests (hermetic, no network):

```bash
pip install -r requirements-dev.txt && python -m pytest
```

## Deploy (Render free)

Render → **New → Blueprint** → this repo. `render.yaml` creates the web service and a free Postgres and wires `DATABASE_URL`. Paste the three API keys (without quotes) when prompted. Check `/health`: it should report `"storage": "postgresql"`.

## Repository map

This repo is an [ICM workspace](https://github.com/RinDig/icm-architect): start at [`AGENTS.md`](AGENTS.md).

```
app/        core/ (models, world+monitor, planner, agent loop, session) · sim/ (systems, tools+contracts, audit)
            llm/ (failover client) · store/ (event-sourced DB) · ui/ (Gradio, Navy theme) · main.py (API)
tests/      unit + end-to-end scenario tests
stages/     01_spec → 02_build → 03_verify → 04_deploy → 05_submit (each with CONTEXT.md)
_shared/    brief, domain, invariants, theme, decisions
docs/       architecture, failure test, thesis, notes
```

MIT licensed.
