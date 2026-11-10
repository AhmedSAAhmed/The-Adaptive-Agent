# 01_spec - decide what we build

One job: turn the brief into a scoped plan with scenarios, architecture and decisions.

## Inputs
- Reference (every run): `../../_shared/brief.md`
- Reference (every run): `../../_shared/domain-doo.md`
- Reference (every run): `../../_shared/decisions.md`

Do NOT load: `app/` source, `docs/`, other stages.

## Process
1. If the brief or decisions are missing, stop and say which.
2. Map every rubric line to something built; keep the "Disqualified" list in view.
3. Record new decisions in `_shared/decisions.md`, not here.

## Outputs
- `plan.md` -> `output/`

## Check
A person reads `output/plan.md` against the rubric in `_shared/brief.md` and confirms every weighted criterion has an owner.
