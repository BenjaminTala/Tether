---
name: trade-management
description: Manage an open position from entry to exit - stop placement, trailing, partial profit taking, time stops and thesis invalidation. Use on every daily check and whenever a held position is discussed. Entries are optional; exits are mandatory.
---

# Trade Management

## Principle
The entry is the least important decision in a trade. Expectancy is dominated by how losses
are cut and how winners are allowed to run. Every position must have, at the moment of entry,
a stop, a target or trailing rule, a time limit, and a written invalidation condition.

## At entry - define all four
1. **Initial stop**: `entry - k*ATR(20)` (default k=2.0 trend, 2.5 spec), or the structural
   level (below the base / prior swing low) if that is tighter. Never wider than the mandate cap.
2. **Profit rule**: trend - sell half at +2R, then trail the remainder. Spec - sell at the
   target R-multiple from the mandate.
3. **Time stop**: if the thesis has not begun to work within N sessions (default 10 spec,
   30 trend) and the position is flat-to-negative, exit and free the capital. Dead money is
   an opportunity cost, not a neutral outcome.
4. **Invalidation**: one falsifiable sentence written at entry - "exit if guidance is cut",
   "exit if it closes below the 50-day for two sessions". Vague theses cannot be invalidated
   and therefore cannot be exited rationally.

## While open
- **Never widen a stop.** Ever. Widening converts a planned small loss into an unplanned large one.
- **Never average down.** Adding to a loser is the single most reliable account-killer in the
  retail canon. Adding to winners (pyramiding) is permitted only if total heat stays in budget
  and the add carries its own stop.
- **Move to breakeven** after +1R, but not before - premature breakeven stops turn winners into
  scratches by denying normal noise.
- **Trailing**: after the +2R partial, trail on `max(3*ATR(20) below high, 20-day low)`.
  Choose one method in the mandate and never switch mid-trade.
- **Gap handling**: if price gaps through the stop, exit on the open at market-limit; do not
  "wait for a bounce". The stop was the decision; the gap is just the price of that decision.

## Exit checklist (daily)
For each open position, evaluate in this order and stop at the first hit:
1. Stop hit -> exit full.
2. Invalidation condition met -> exit full, regardless of P&L.
3. Time stop expired and position < +0.5R -> exit full.
4. Target / partial level reached -> execute partial, reset trailing.
5. Regime downgraded to risk-off -> begin scaling out per mandate.
6. None of the above -> hold, change nothing.

## Language discipline
Record exits as "stop hit" or "thesis invalidated", never as "shaken out" or "unlucky".
The vocabulary you use to describe outcomes shapes the next decision.

## Provenance
Faith, *Way of the Turtle* and the Turtle rules (N-based stops, no discretion on exits);
Elder, *The New Trading for a Living* (the two-percent and six-percent style constraints);
Minervini, *Trade Like a Stock Market Wizard* (stop discipline, selling into strength);
Schwager, *Market Wizards* (near-universal agreement across interviewees on cutting losses).
