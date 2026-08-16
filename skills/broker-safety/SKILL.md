---
name: broker-safety
description: Rules for connecting to Interactive Brokers safely from an automated agent - port discipline, paper/live separation, dry-run defaults, order hygiene and reconciliation. Consult before any code touches the broker connection, and whenever a connection error occurs.
---

# Broker Safety (IBKR)

## Principle
The most expensive bug in an automated trading system is not a bad trade. It is a correct
trade sent to the wrong account. Every design decision here optimises for making that
impossible rather than for convenience.

## Port discipline — the non-negotiable rule
| Client | Paper | Live |
|---|---|---|
| TWS | 7497 | 7496 |
| IB Gateway | 4002 | 4001 |

- The port is set explicitly in config and **must match a `mode: paper|live` field** that is
  also set explicitly. A mismatch is a startup crash, not a warning.
- **Never fall back to another port on connection failure.** Several published IBKR skills
  retry the "other" port when the configured one fails and remember which worked. In an
  automated system that is a silent paper-to-live failover — exactly the failure this skill
  exists to prevent. A failed connection is a failed cycle: alert and stop.
- On connect, read the account ID and assert it matches the configured one. Paper accounts are
  prefixed `DU`. If `mode: paper` and the account ID does not start with `DU`, disconnect
  immediately and alert.
- Live mode additionally requires a `LIVE_TRADING_CONFIRMED=yes` environment variable set by
  hand. Config alone must not be able to arm live trading.

## Dry-run by default
Every order-placing path takes `--execute`. Without it, the code computes and logs the exact
orders it would send and places nothing. The scheduler passes `--execute` only for the live
cycle; every test, backfill and manual run defaults to dry.

## Order hygiene
- **Idempotency**: derive a deterministic client order ID from `(cycle_id, ticker, action)`.
  Re-running a cycle must not double-fill.
- **Never bare market orders.** Use marketable limits with a band from the mandate (default
  0.5% through the touch). A market order at the open of a thin instrument is a donation.
- **Orphan cleanup before placement**: cancel stale working orders for the ticker before
  submitting a new one, and log what was cancelled. Never leave two stops on one position.
- **Fractional shares**: IBKR fractional orders support only certain order types — verify at
  implementation and treat protective stops on fractional positions as software-managed by the
  daily loop, not as resting broker orders.
- **Cash account**: track `SettledCash`, not `BuyingPower`. Proceeds are unavailable until
  settlement. Sizing off buying power in a cash account produces violations, not leverage.

## Reconciliation — before and after every cycle
1. Fetch positions and open orders from IBKR.
2. Diff against the internal journal.
3. Any discrepancy (unknown position, missing position, unexpected order, quantity mismatch)
   → halt the cycle, place nothing, alert. Do not "correct" the difference automatically;
   an unexplained position may mean the journal is wrong or the broker state is stale, and
   guessing which is how small errors become large ones.
4. After execution, re-fetch and confirm fills match intent. Log both.

## Connection lifecycle
- IB Gateway restarts daily; schedule cycles clear of the restart window and treat a
  connection failure during it as expected, not as an error to retry aggressively.
- One connection per cycle, explicitly closed. Unique `clientId` per process; a collision
  silently steals the other session's messages.
- Wrap all of it behind a `Broker` interface with paper, live and simulated implementations so
  that the same code path is exercised in testing as in production.

## Kill switch
A file at a known path (or a message command) that, when present, causes every cycle to exit
before placing orders. Checked first, before anything else, including before connecting.
The agent must never create, move, or delete this file.

## Adapted from
`ib-portfolio`, `ib-stop-loss` and related skills in staskh/trading_skills (MIT). Kept: the
port table, dry-run-by-default with an explicit `--execute`, and orphan-order cancellation
before placing new protective orders. **Rejected: the automatic port fallback and the
"remember which account type worked" behaviour** — sensible for an interactive human advisor,
unacceptable in an unattended loop. Added: account-ID assertion, live-mode env confirmation,
idempotent order IDs, settled-cash handling and mandatory reconciliation.
