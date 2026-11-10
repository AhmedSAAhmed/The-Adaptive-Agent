# The Adaptive Agent

A customer-service action agent (DOO-style: WhatsApp refunds and bookings) that notices reality changed and safely changes its plan. What leaves this repo: a live demo on Render and a challenge submission.

## Where things live

| Folder | What it holds |
|---|---|
| `app/` | product: the running system (FastAPI + Gradio, agent loop, store, sim systems) |
| `tests/` | the check for `app/`: `python -m pytest` |
| `stages/` | the build-and-ship pipeline, in execution order |
| `_shared/` | factory: brief, rubric, domain, invariants, theme, decisions (stable) |
| `_templates/` | blank starters: a new scenario or stage is a copy, not a blank page |
| `_tools/` | `links.py` checks every link and input path in the markdown |
| `docs/` | submission deliverables judges read (architecture, failure test, thesis, notes) |

## Route by what just happened

| If | Go to | Then stop at |
|---|---|---|
| changing the plan or scope | [01_spec](stages/01_spec/CONTEXT.md) | the spec check |
| writing or fixing code | [02_build](stages/02_build/CONTEXT.md) | `pytest` green |
| checking the demo end to end | [03_verify](stages/03_verify/CONTEXT.md) | a person signs `check.md` |
| shipping to Render | [04_deploy](stages/04_deploy/CONTEXT.md) | live `/health` ok |
| preparing the submission | [05_submit](stages/05_submit/CONTEXT.md) | checklist ticked |
| adding a demo scenario | [_templates/scenario.md](_templates/scenario.md) | its test in `tests/test_scenarios.py` |
| asked for status | scan `stages/*/output/` and any `check.md` | report what exists |

## The one rule

Nothing moves to the next stage until the last one's check passes. Never commit `.env`; never add AI co-author trailers to commits.
