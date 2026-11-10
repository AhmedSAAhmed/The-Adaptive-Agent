# Failure test - when adaptation itself goes wrong (Scenario C)

## The failure
Adaptation is only as good as the signals it adapts to. In Scenario C a faulty courier integration flips `order.ORD-9902.status` between `picked_up` and `preparing` every ~0.8 s, while the order is really still in the kitchen.

The **naive adaptive agent** does everything "right" by the textbook: it observes, sees a contradiction, and re-plans. That is exactly the problem:
- it abandons the cancellation the customer is entitled to because a bad signal said "picked up",
- it re-plans on each flip, burning LLM calls and its own revision budget,
- the customer gets a different story each time it changes its mind.

The audit (against the order system of record) marks it **Wrong outcome**: the customer was denied a valid cancellation, or got contradictory compensation.

## The containment (guarded agent, same events)
| Layer | What it does | Code |
|---|---|---|
| Confirm before believing | A low-trust event is checked against the system of record. If they disagree, the event is recorded as `unconfirmed`, the belief is set from the system of record, and the plan is **not** changed. The trace says "I did NOT change my mind because…". | `Agent._on_event` |
| Flap detection | 3+ flips of a key in 30 s marks the source unhealthy and opens an ops ticket. From then on that source must always be confirmed. | `FlapDetector`, `Agent._on_event` |
| Revision budget | At most 3 re-plans per mission. Past that: freeze irreversible steps, hand off to a human with the trace. | `Agent._revise`, `_escalate` |
| Pre-commit re-check | Right before an irreversible step, its contract is re-read from the system of record, so even a change no event announced cannot slip through. | `Agent._loop` |
| Validated plans | LLM plans are rebuilt from the tool registry. Unknown tools, refunds above total, vouchers above 25%, confirming a moved booking without asking, or calling an irreversible tool whose contract is already false are rejected → deterministic plan. | `planner.validate` |
| Provider failover | Groq → OpenRouter → Gemini → deterministic, with a circuit breaker. An LLM outage degrades plan quality, never safety. | `LLMClient` |

Result: the guarded agent cancels and refunds correctly, sends one message, and leaves an ops ticket naming the broken integration.

## Residual risks (not solved, stated honestly)
- **A wrong system of record.** If the authoritative source is wrong, confirmation confirms the error. Mitigation in production: reconciliation jobs and human review for high-value actions.
- **Slow true changes look like noise.** The flap window could delay acceptance of a real, rapidly changing status. The threshold is a tunable trade-off.
- **LLM judgement inside the safe set.** Validation guarantees safety, not optimality: an LLM may still choose a weaker (but valid) remedy, e.g. 10% vs 25% voucher.
- **Single instance.** Sessions live in one process (fine for the free tier); horizontal scaling would need the inbox on a shared queue.

## Tests that pin this down
`tests/test_scenarios.py`: `test_c_flapping_signal_is_contained`, `test_revision_budget_escalates_to_human`, `test_precommit_recheck_catches_change_the_monitor_never_saw`; `tests/test_planner.py`: validator rejections and LLM-to-deterministic fallback.
