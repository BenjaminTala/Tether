---
name: market-regime
description: Determine the current market regime (risk-on / neutral / risk-off) and the resulting exposure ceiling before any buy decision is made. Use at the start of every weekly cycle, and whenever an index-level shock occurs. Regime sets HOW MUCH risk is allowed; other skills decide WHAT to buy.
---

# Market Regime & Exposure Ceiling

## Principle
Position size is a function of the environment, not of conviction. Most drawdowns come from
being fully invested in a hostile tape, not from picking the wrong stock in a friendly one.
Decide exposure first, instruments second.

## Inputs (all fetched via tools — never from memory)
- SPY and QQQ: close vs 200-day SMA and 50-day SMA; 200-day slope over last 20 sessions.
- Breadth proxy: % of S&P 500 above their 200-day SMA (or RSP/SPY ratio trend as fallback).
- Volatility: VIX level and 20-day change.
- Credit/defensive tone: HYG vs IEF ratio trend; XLU/XLP vs SPY relative strength.
- Distribution days: sessions in the last 25 where SPY or QQQ closed down >=0.2% on higher
  volume than the prior day. (O'Neil/IBD construct.)

## Classification
Score each of the five inputs +1 (supportive), 0 (neutral), -1 (hostile).

| Total | Regime | Max invested (non-core) | New entries |
|---|---|---|---|
| >= +3 | Risk-on | 100% of trend+spec budget | Allowed |
| 0 to +2 | Neutral | 60% | Trend only, half size |
| -1 to -2 | Caution | 30% | Trend only, half size, no spec |
| <= -3 | Risk-off | 0% | None. Existing positions trail out. |

Rules:
- A regime downgrade takes effect immediately; an upgrade requires two consecutive cycles.
  Downgrades are cheap, upgrades are expensive.
- 5+ distribution days in 25 sessions forces at least Caution regardless of score.
- The safety core sleeve is NEVER reduced by regime. Regime only governs trend + speculative.
- Regime never forces a buy. A risk-on reading is permission, not an instruction.

## Output (structured)
`{regime, score, per_input_scores, exposure_ceiling_pct, new_entries_allowed, one_line_rationale}`

## Failure modes
- Whipsaw: flipping regime weekly on small moves. Require the score to cross a boundary, not touch it.
- Retrofitting: choosing inputs after seeing which would have worked. Inputs are fixed in the mandate.
- Confusing regime with forecast. This is a description of the present, not a prediction.

## Provenance
Trend-filter logic: Faber, "A Quantitative Approach to Tactical Asset Allocation" (2007);
Antonacci, *Dual Momentum Investing*. Distribution-day and follow-through-day construct:
O'Neil, *How to Make Money in Stocks*. Exposure-tiering discipline: Minervini; Elder.
