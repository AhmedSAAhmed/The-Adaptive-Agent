# Two-year thesis: adaptive planning in production agents

By 2028 the hard part of production agents will not be planning. It will be knowing when a plan has stopped being true. Today most agents treat a plan as a script. Tomorrow's agents will treat it as a set of bets on the world, and each bet will have an owner, a source and an expiry.

Three shifts follow.

**1. Assumptions become first-class, typed and owned by code.** Every irreversible tool ships with a contract: what must be true for it to be safe. Change detection becomes a cheap lookup on the keys a plan depends on, not an LLM call on a timer. Models will be asked *what to do now* only after code has proven that something changed. That makes adaptation both cheaper and auditable.

**2. Trust in signals will be as important as trust in models.** As agents act on webhooks, feeds and other agents' outputs, the main failure is no longer hallucination but believing a bad signal. Production stacks will carry trust levels, confirmation against systems of record, flap detection and revision budgets, the same way SRE teams carry alert de-duplication and escalation policies today. An agent that changes its mind too easily is as dangerous as one that never does.

**3. "Why I changed my mind" becomes a compliance artifact.** In customer service, payments and bookings, regulators and customers will expect an event-sourced record: the trigger, the broken assumption, the old and new plan, and who (model, rule or human) decided. Revision traces will be the unit of review, of evaluation and of model improvement.

The winners will not be the agents with the cleverest planners. They will be the ones whose plans fail loudly, early and safely, and whose humans step in at the right moment, with the full story already written.
