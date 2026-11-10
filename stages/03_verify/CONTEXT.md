# 03_verify - watch it work live

One job: run all three scenarios in the real UI with the real LLM chain and confirm the before/after is obvious.

## Inputs
- Working (this run): the app started with `python -m uvicorn app.main:app --port 7860`
- Reference (every run): `../../_shared/brief.md` (Demo quality, Failure thinking)

Do NOT load: `stages/05_submit/`, deploy config.

## Process
1. Run A, B, C side by side. For each, note the baseline/naive verdict, the adaptive verdict, the revision reasons (EN + AR) and the LLM provider used.
2. During a run, inject one event from the accordion or with `curl` (see the Architecture tab).
3. Open one `trace.md` link and confirm it matches the screen.

## Outputs
- `run-notes.md` -> `output/`

## Check
A person writes `output/check.md`: first line `pass` or `fail: <why>`.
