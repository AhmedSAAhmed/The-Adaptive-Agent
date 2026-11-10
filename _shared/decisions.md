# Decisions - answers to the plan's open questions (2026-11-10)

| # | Question | Decision |
|---|---|---|
| 1 | LLM? | Yes, production-style. OpenAI-compatible failover chain: Groq (`openai/gpt-oss-120b`) → OpenRouter (`anthropic/claude-sonnet-5.5`) → Gemini (`gemini-3.5-flash`) → deterministic planner. Circuit breaker per provider. Groq made primary on 2026-11-10 (lower latency; OpenRouter credits ran low). Override with `LLM_CHAIN`. |
| 2 | Scenarios | A refund after dispatch, B branch closes early, C flapping courier signal (failure test). |
| 3 | Database | Postgres on Render (blueprint-provisioned); SQLite locally. Event-sourced tables. |
| 4 | ECC / icm-architect | Local tooling only: installed under `.claude/` (gitignored). The ICM structure (`AGENTS.md`, contracts) is committed. |
| 5 | Navy theme | Tokens reused; non-commercial demo. |
| 6 | GitHub | Push to `AhmedSAAhmed/The-Adaptive-Agent`; no AI co-author trailers. |
| 7 | Language | Every customer message in English and Arabic. |
| 8 | Video | Recorded by the owner; no auto-play demo mode. |
| 9 | Judge input | "Try it yourself" tab (2026-11-10): own request (EN/AR) + chosen twist + human customer replies, scoped to refunds and bookings. Scripted A/B/C stay the default. |

Change detection is never delegated to the LLM: assumptions are predicates, checked by code on each event. The LLM only proposes what to do next, and code validates it.
