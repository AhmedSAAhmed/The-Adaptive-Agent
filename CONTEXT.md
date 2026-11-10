# The Adaptive Agent - the pipeline

The flow in one line: spec it, build it, verify it live, ship it to Render, submit it.

| Stage | Job |
|---|---|
| `01_spec` | decide scope, scenarios and architecture |
| `02_build` | write code until tests pass |
| `03_verify` | watch all scenarios run live |
| `04_deploy` | ship the blueprint to Render |
| `05_submit` | video, thesis, notes, submission form |

Each stage's own `CONTEXT.md` holds its inputs, outputs and check.

Factory (stable, every run): `_shared/brief.md`, `_shared/domain-doo.md`, `_shared/invariants.md`, `_shared/theme.md`, `_shared/decisions.md`
Product (new each run): `app/`, each stage's `output/`, and `docs/` (deliverables).

Deliberate break of invariant 5 (product lives in stage output): the code lives in `app/` and the judge-facing deliverables in `docs/`, because a clean clone, Render and the judges expect those conventional paths. The stages point at them.

Status is whatever exists: a stage is complete when its outputs exist and any `check.md` there says pass.
