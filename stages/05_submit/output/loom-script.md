# 90-second walkthrough script

Setup: open the live URL a minute early (free tier cold start). Scenario A selected. Browser at ~1280 px wide.

| Time | Show | Say |
|---|---|---|
| 0–10 s | Hero | "Agents commit to a plan and execute it blindly. This one checks, on every incoming signal, whether its plan is still true." |
| 10–20 s | Press **Run side by side** (A) | "Same plan, same tools, same event stream. Left never re-checks. Right is the adaptive agent." |
| 20–40 s | Event stream: `order_system picked_up` → right panel re-planning | "The courier just picked up the food. That breaks the refund's contract: refunds only for food that never left. The left agent refunds SAR 186 and reports success. That's a silent failure." |
| 40–50 s | "I changed my mind because…" card | "Every revision says what changed, which assumption broke, and what it does instead, in English and Arabic, and it's stored in Postgres." |
| 50–75 s | Run **C** | "Now the failure test: a broken courier integration flips the status every second. The naive agent believes it and thrashes. The guarded agent confirms against the system of record, ignores the noise, flags the source after three flips, and still refunds correctly." |
| 75–85 s | Architecture tab, then `curl` to `/api/events` | "Plan, execute, observe, re-evaluate. Events come in by webhook, so anyone can break a run live." |
| 85–90 s | Run history / repo | "Code, traces and tests are in the repo." |
