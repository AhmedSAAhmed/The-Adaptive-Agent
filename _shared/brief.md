# Brief - the challenge and how it is scored

Source: build.doo.ooo/challenges/adaptive-agent ("Can an AI system recognize that reality changed and safely change its mind?").

## Build
- An agent that runs a multi-step plan and continuously checks whether its world model is still valid.
- Re-planning triggers when new signals contradict prior assumptions (not on a fixed timer).
- A visible "I changed my mind because…" trace for every revision.
- At least 2 demo scenarios where the original plan would have failed silently if not adapted.

## Deliverables
- Working build: public repo (clean clone runs) + live demo URL (required).
- 90-second video of one adaptive run end to end (optional, recommended).
- Architecture snapshot: plan → execute → observe → re-evaluate loop.
- Failure test: one scenario where adaptation goes wrong, and how it is contained.
- Two-year thesis (≤300 words) on adaptive planning in production agents.
- Notes: AI tools used, key decisions, out of scope.

## Rubric
| Weight | Criterion | Looks for |
|---:|---|---|
| 25 | Conceptual clarity | adaptation is mission-driven, not random re-prompting |
| 25 | Technical depth | real plan/observe/revise loop with persisted state |
| 20 | Demo quality | the before/after of adaptation is obvious in 90 s |
| 15 | Failure thinking | where adaptation fails and how it is handled |
| 15 | Future thesis | sharp view on adaptive agents in production |

Bonus: side-by-side with a non-adaptive baseline; streaming/event-driven inputs.
Disqualified: "re-prompt every N seconds" with no change detection; no demo, broken repo, hidden logic.
