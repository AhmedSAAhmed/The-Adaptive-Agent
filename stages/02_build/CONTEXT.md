# 02_build - code until tests pass

One job: change `app/` so the agent meets the plan and the invariants.

## Inputs
- Working (this run): `../01_spec/output/plan.md`
- Reference (every run): `../../_shared/invariants.md`
- Reference (every run): `../../_shared/theme.md` (UI work only)

Do NOT load: `docs/`, `stages/05_submit/`, the whole `.claude/` skill tree (load one skill when a task needs it).

## Process
1. Map of `app/`: `core/` (models, world + monitor, planner, agent loop, session), `sim/` (systems, tools + contracts, audit), `scenarios/` (scripted A/B/C + `custom.py` for "Try it yourself"), `llm/` (failover client), `store/` (event-sourced DB), `ui/` (Gradio + Navy theme), `main.py` (API + mount).
2. New tool → add a `ToolSpec` with its contract in `app/sim/tools.py`. New scenario → copy `../../_templates/scenario.md`.
3. Keep change detection in code; the LLM only proposes plans that `validate()` rebuilds.
4. Run `python -m pytest`.

## Outputs
- Changed files in `app/` and `tests/`.

## Check
`python -m pytest` exits 0 (hermetic: no network, deterministic planner). Then `python -I _tools/links.py` passes.
