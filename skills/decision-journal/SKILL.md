---
name: decision-journal
description: Write and review the trade journal - recording each decision at the time it is made, and scoring outcomes in R-multiples and process quality afterwards. Use at every decision, on every close, and in the monthly review. This is the agent's only genuine learning mechanism.
---

# Decision Journal & Postmortem

## Principle
Without a record written *before* the outcome is known, every review is contaminated by
hindsight. The journal exists to make past reasoning auditable and to separate good decisions
from good outcomes - which are different things and frequently uncorrelated in the short run.

## Write at decision time (never after)
```yaml
id: 2026-08-15-XLE-01
timestamp: ...
sleeve: trend|speculative|core
action: enter|add|trim|exit|no_action
ticker: XLE
regime_at_decision: {regime: neutral, score: 1}
thesis: "one or two sentences, falsifiable"
invalidation: "specific, observable condition"
evidence: [ {source, what_it_showed} ]      # tool outputs only, no recalled figures
expected: {target_R: 2.0, horizon_sessions: 20, probability: 0.4}
risk: {entry, stop, shares, risk_dollars, pct_equity, heat_after}
alternatives_considered: ["...", "..."]
confidence: 0.55
```

## Write at close
```yaml
outcome: {exit_price, exit_reason: stop|invalidation|target|time|regime, R_multiple: -1.0}
mae_R: -1.1        # max adverse excursion in R
mfe_R: 0.8         # max favourable excursion in R
process_score: 0-5 # adherence to rules, INDEPENDENT of P&L
lesson: "one sentence, or 'none - sample too small'"
```

## Scoring rules
- **Process score is not outcome score.** A losing trade taken correctly, sized correctly and
  exited at the stop is a 5. A winning trade taken on a widened stop is a 1. Reward the process.
- **Expectancy** = `avg_R_win * win_rate - avg_R_loss * (1 - win_rate)`. Track it per sleeve.
  A system with a 35% win rate and 3R winners is healthy; do not "fix" the win rate.
- MFE >> realised R repeatedly means exits are too tight. MAE regularly near the stop on
  winners means entries are early, not that stops are too tight.

## Sample-size discipline
- Below ~30 closed trades per sleeve, draw NO conclusions about edge. State this explicitly in
  reviews rather than inventing a narrative from 6 trades.
- Never change a rule on the basis of a single loss or a single win. Rule changes require a
  documented pattern across at least 20 trades, and go to the human for approval.

## Monthly review output
Equity curve vs benchmarks, per-sleeve expectancy and R distribution, cost ratio, rule
violations (count and description), open risk over time, and one proposed adjustment with the
evidence for it - or an explicit "no change warranted".

## Provenance
Van Tharp (R-multiples, expectancy, process over outcome); Schwager, *Market Wizards*
(journaling as the common habit); Kahneman, *Thinking, Fast and Slow* (hindsight bias, the
outcome/decision distinction); Duke, *Thinking in Bets* (resulting); Davey, *Building Winning
Algorithmic Trading Systems* (sample size, out-of-sample discipline).
