# Domain - why DOO, and what the agent acts on

DOO runs AI customer-service agents on WhatsApp, voice and chat for brands in Saudi Arabia and the GCC. Its agents answer in the customer's language and **take actions inside business systems**: refunds, cancellations, bookings.

That is where static plans break. Between "the customer asked" and "the agent acted", the world moves: couriers pick up orders, branches close early, integrations misfire. An action agent that does not re-check its assumptions either loses money silently or makes promises nobody can keep.

## Systems simulated in `app/sim/`
| System | Keys in the world model | Trust |
|---|---|---|
| Order system of record | `order.<id>.status`, `order.<id>.total` | high (authoritative) |
| Signed order-system webhook | `order.<id>.status` | high |
| Courier app webhook | `order.<id>.status` | low (must be confirmed) |
| Branch ops feed / booking API | `branch.<b>.open_until`, `branch.<b>.slot.<HH:MM>` | high |
| WhatsApp | `customer.reply` | high |
| Agent's own state | `booking.active_hold`, `booking.confirmed` | checked only at pre-commit |

## Customer messages
Every customer-facing message is written in English and Arabic (Gulf-friendly, short, WhatsApp tone).
