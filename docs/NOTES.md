# Notes for judges

## What to look at
1. **Live demo, Scenario A**: the baseline refunds SAR 186 for food already on its way and reports success; the adaptive agent's `cancel_order` contract breaks on the courier webhook and it re-plans to a voucher + ETA.
2. **Scenario B**: the branch posts an early closure while the table is on hold; the adaptive agent releases the hold, moves to another branch, asks the guest in Arabic and English, then confirms.
3. **Scenario C (failure test)**: a flapping courier webhook; the naive adaptive agent thrashes, the guarded agent confirms against the system of record and contains it. See `docs/FAILURE_TEST.md`.
4. **Break it yourself**: during a run, `POST /api/events` (Architecture tab has the `curl`), or use the "Inject a real-world event" panel.
5. **Traces**: every run has a `trace.md` link; Run history lists stored sessions with audited verdicts.

## Key decisions
- **Code detects change; the LLM decides what to do next.** Assumptions are typed predicates. Tool contracts are attached by code, so an LLM cannot drop the precondition of a refund.
- **Safe points.** Re-planning happens between steps; irreversible steps get a pre-commit re-check against the system of record.
- **Honest comparison.** Same plan, tools and events for both runs; outcomes judged against the system of record, not the agent's beliefs.
- **Production-style LLM layer.** Groq (gpt-oss-120b) → OpenRouter (Claude Sonnet 5.5) → Gemini → deterministic planner, with timeouts, a circuit breaker and every call logged.
- **Event-sourced Postgres** for runs, events, plan versions, revisions, steps and LLM calls.
- **Bilingual by default.** Every customer message in English and Arabic, as DOO serves the GCC.

## AI tools used
- Claude Code (Claude Opus 5.5) as a pair programmer for architecture, code, tests and docs.
- Runtime LLMs: gpt-oss-120b via Groq (primary, low latency), Claude Sonnet 5.5 via OpenRouter, Gemini 3.5 Flash.
- Firecrawl to research the brief, DOO's product and the Navy theme tokens.
- Workspace method: icm-architect (folder structure as agent architecture: `AGENTS.md`, stage contracts); selected ECC skills/rules (TDD, verification loop, Python patterns, security review) used locally.

## Out of scope
- Real DOO / courier / restaurant integrations (simulated systems with the same shapes).
- Authentication and multi-tenant isolation in the demo UI (the webhook supports an optional `WEBHOOK_TOKEN`).
- Horizontal scaling (single instance on Render free; sessions live in-process, history in Postgres).
- Voice channel; only WhatsApp-style text.
