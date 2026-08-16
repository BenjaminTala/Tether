---
name: execution-gate
description: The final deterministic gate every proposed order passes through before it reaches the broker. Consumes the regime, circuit-breaker and sizing artifacts and emits GO / NO_GO / REVIEW_REQUIRED. Runs as code, not as judgement - the model cannot argue with it.
---

# Execution Gate

## Principle
The model proposes; the gate disposes. Every rule that protects capital lives here as code
with tests, because a rule that lives only in a prompt is a suggestion. The gate's default
answer is no: it must find affirmative evidence that a trade is permitted, not merely fail to
find a reason to block it.

## Position in the pipeline
```
market-regime ──> exposure_decision.json ─┐
circuit-breaker ─> circuit_breaker.json ──┼──> EXECUTION GATE ──> orders | no_action
model proposal ──> decision.json ─────────┤
position-sizing ─> sizing.json ───────────┘
```
Every upstream artifact must exist, be schema-valid, and be fresh (default: produced within
the last 60 minutes). A missing or stale artifact is `REVIEW_REQUIRED`, never `GO`.

## Blocking checks — an entry is refused if ANY of these hold
1. Circuit breaker is `COOLDOWN`, `HALTED`, `HALTED_MANUAL`, or the sleeve is paused.
2. Regime exposure ceiling is already met or exceeded by current holdings.
3. Ticker is not on the mandate whitelist.
4. No stop price is present, or the stop implies risk above the per-trade budget.
5. `actual_risk_dollars > planned_risk_dollars` (any drift between sizing and order).
6. Portfolio heat after the order would exceed the mandate ceiling.
7. Position or sleeve concentration cap breached.
8. Cost gate failed, or notional is below the minimum viable size.
9. Cooldown active on this ticker (recently stopped out, default 5 sessions).
10. A duplicate order for this ticker exists this session, or an unfilled prior order is open.
11. Settled cash is insufficient (cash account — buying power is not settled cash).
12. Thesis or invalidation field is empty.
13. Any figure in the proposal cannot be traced to a tool call in the originating session.

## Decisions
| Decision | Meaning | Engine behaviour |
|---|---|---|
| `GO` | All checks passed for this order | Place order |
| `NO_GO` | A rule was violated | Skip this order, continue with others, log and alert |
| `REVIEW_REQUIRED` | Inputs missing, stale, or unreadable | Place nothing at all, alert human |
| `NO_ACTIONABLE_ORDERS` | Proposal contained no entries | Normal, common, not an error |

Exit, trim and stop-management orders bypass checks 1, 2 and 8 — reducing risk is always
allowed. They still pass whitelist, duplicate and reconciliation checks.

## Exit codes
Non-`GO` exits non-zero **by default**. There is no flag to make failures silent. A scheduler
that cannot tell the difference between "nothing to do" and "the gate refused" will eventually
be trusted with the wrong one.

## Audit
Every evaluation writes a decision record with the full input snapshot, per-check pass/fail,
and the resulting orders. The record is written *before* orders are transmitted, so a crash
mid-cycle leaves evidence of intent that reconciliation can compare against actual fills.

## Adapted from
`pre-trade-discipline-gate` in tradermonty/claude-trading-skills (MIT). Kept: the artifact
contract, the four-value decision enum, checklist-answer auditing, upstream-artifact
dependency, and the revenge/cooldown concept. Changed: that skill is explicitly a checklist
for a human placing manual orders and does not call a broker; this one sits inline in an
automated path, so failure is non-zero by default rather than opt-in, artifact freshness is
enforced, settled-cash and duplicate-order checks are added, and the model never sees the
gate's internals — it receives only the decision.
