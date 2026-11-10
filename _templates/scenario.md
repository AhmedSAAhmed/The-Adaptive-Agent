# Scenario {ID} - {name}

Copy this file, fill it in, then implement it in `app/scenarios/__init__.py` and add a test in `tests/test_scenarios.py`.

## Mission
- Kind: refund | booking
- Customer request (WhatsApp, EN/AR): {text}
- Goal: {what "done" means}

## Seeded world
- System of record: {orders / branches with values}
- Initial beliefs: {keys the agent starts with}

## Event stream
| at (s, 1.6 s steps) | source | key | value | trust | real? | note |
|---|---|---|---|---|---|---|
| {2.0} | {order_system} | {order.X.status} | {picked_up} | high | yes | {why} |

## Expected
- Static plan: {how it fails silently}
- Adaptive: {which contract breaks, what it does instead}
- Comparison modes: baseline vs adaptive | naive vs adaptive
