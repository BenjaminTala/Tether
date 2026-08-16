---
name: circuit-breaker
description: Account-level loss limits and cooldowns that decide whether ANY new risk may be taken today. Evaluated by deterministic code before every cycle. Produces a circuit_breaker_decision artifact that the execution gate consumes. This is a hard block, not advice.
---

# Circuit Breaker

## Principle
Separate the question "is this a good trade?" from "am I allowed to trade at all right now?"
The second question is answered first, by arithmetic over the journal, and its answer is
binding. A trading system that can talk itself past its own loss limits does not have loss limits.

## Inputs
Journal state only (closed and open theses with realized/unrealized P&L, timestamps, exit
reasons) plus current equity from the broker. No market data, no network, no model.

## Rules (tuned for a $1000 cash account — see mandate for live values)

| Rule | Trigger | State | Release |
|---|---|---|---|
| Daily loss | realized+unrealized -3% of equity in one session | `HALTED` | Next trading day open |
| Losing streak | 3 consecutive terminal losses | `COOLDOWN` | 48h after the last losing exit |
| Weekly drawdown | -7% from Monday open | `HALTED` | Next Monday |
| Monthly drawdown | -10% from month start | `HALTED` | First trading day of next month |
| High-water drawdown | -15% from all-time equity high | `HALTED_MANUAL` | Human restart only |
| Sleeve drawdown | -20% in trend or speculative sleeve | `SLEEVE_PAUSED` | 30 days, that sleeve only |
| Loss-recovery guard | any drawdown >10% from high-water | `HALF_RISK` | New equity high |

Thresholds are wider in percentage terms than a large account's because the trade count is
tiny — with 3-6 open positions, a 2% daily rule would fire on ordinary noise and the system
would spend most of its life halted. Widen the percentage, never the number of consecutive losses.

## States and what they permit
- `TRADING_ALLOWED` — normal operation.
- `HALF_RISK` — new entries allowed at half the mandate risk budget.
- `COOLDOWN` — no new entries. Exits, trims and stop management continue normally.
- `SLEEVE_PAUSED` — no new entries in that sleeve; other sleeves unaffected.
- `HALTED` — no new entries anywhere. Existing positions managed to their stops.
- `HALTED_MANUAL` — flatten to core/cash. Requires a human to clear. The agent may not clear it,
  may not argue for clearing it, and may not propose a mandate change that would clear it.

Exits are NEVER blocked by a circuit breaker. Reducing risk is always permitted in every state.

## Fail-closed rule (critical)
If journal state is missing, unparseable, internally inconsistent, or if any thesis has a
realized-P&L entry that is absent or non-finite, the decision is `HALTED` with
`data_quality: PARTIAL`. Repair the state and re-run. The one exception is a genuinely empty
journal on first run, which returns `TRADING_ALLOWED` with `data_quality: EMPTY_STATE`.

A system that treats "I couldn't read my own P&L" as "probably fine" will eventually read it
wrong on the day it matters.

## Timezone
All day/week/month boundaries in `America/New_York`, on the exchange calendar, not local time
and not UTC. A `--as-of` override exists for tests and backfills only; it must never be set by
the scheduler.

## Output artifact
```json
{"as_of": "...", "recommendation": "TRADING_ALLOWED|HALF_RISK|COOLDOWN|SLEEVE_PAUSED|HALTED|HALTED_MANUAL",
 "triggered_rules": [{"rule": "weekly_drawdown", "value": -0.081, "limit": -0.07}],
 "sleeves_paused": [], "risk_multiplier": 1.0, "data_quality": "OK|PARTIAL|EMPTY_STATE",
 "release_condition": "next Monday 2026-08-17", "equity": 1043.22, "high_water": 1180.05}
```

## Adapted from
`drawdown-circuit-breaker` in tradermonty/claude-trading-skills (MIT). Kept: state-file-only
evaluation, fail-closed on partial data, ET boundaries, `--as-of` determinism, explicit release
conditions. Changed: thresholds re-tuned for a small account and low trade count; added
sleeve-level and high-water tiers; **removed the "recommendation, not enforcement" framing** —
in this system the artifact is binding and the execution engine refuses to place entry orders
without a passing one.
