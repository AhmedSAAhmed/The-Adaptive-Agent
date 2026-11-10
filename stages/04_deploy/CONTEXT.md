# 04_deploy - ship to Render free

One job: get a public URL anyone can open.

## Inputs
- Working (this run): `../../render.yaml`, `../../requirements.txt`, `../../.python-version`
- Reference (every run): `../../.env.example` (variable names; values come from the owner's `.env`)

Do NOT load: `app/` internals, `docs/`.

## Process
1. Render dashboard → New → Blueprint → pick `AhmedSAAhmed/The-Adaptive-Agent`. It creates the web service and the free Postgres and wires `DATABASE_URL`.
2. Paste `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY` **without quotes**.
3. Wait for the build, then open `/health`: expect `"storage": "postgresql"` and three providers.
4. Free tier sleeps after ~15 min idle; open the URL ~1 minute before anyone judges it.

## Outputs
- `live-url.md` -> `output/` (the URL and the date it was verified)

## Check
`curl <url>/health` returns `ok: true` with `storage: postgresql`; one scenario completes in the browser.
