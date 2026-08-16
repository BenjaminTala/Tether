---
name: trend-selection
description: Rank and select instruments for the trend sleeve using time-series and cross-sectional momentum. Use during the weekly cycle after market-regime has set the exposure ceiling. Produces a ranked candidate list, not orders.
---

# Trend & Momentum Selection

## Principle
Two independent, well-documented effects:
- **Time-series momentum (absolute):** an asset's own past 12-month return predicts its next
  months. Used as a gate — do not own something in a downtrend.
- **Cross-sectional momentum (relative):** among assets that pass the gate, the strongest
  recent performers tend to keep outperforming over 1-12 months.
Combine: gate first, then rank. Never rank without gating; relative strength inside a bear
market just selects the least-bad loser.

## Procedure
1. **Universe** — only tickers on the mandate whitelist. Reject anything else, always.
2. **Absolute gate** — keep candidates where ALL hold:
   - 12-month total return > return of the cash/T-bill proxy (BIL/SGOV) over the same window
   - price > 200-day SMA
   - 200-day SMA not declining over the last 20 sessions
3. **Rank** survivors by a blended score:
   `0.4*r_12m + 0.4*r_6m + 0.2*r_3m`, each measured excluding the most recent 5 sessions
   (skip-recent reduces short-term reversal contamination).
4. **Quality filters** — drop any candidate with:
   - median 20-day dollar volume below the mandate liquidity floor
   - earnings inside the next 5 sessions (trend sleeve only; earnings are the spec sleeve's business)
   - price more than 1 ATR(20) above its 20-day SMA (extended — wait for the next cycle)
5. **Correlation cap** — if two candidates have 60-day correlation > 0.80, keep the higher-ranked
   one only. Three tech ETFs are one bet wearing three hats.
6. **Select** top N per the mandate (default 3-4), equal risk-weighted (see position-sizing).

## Turnover discipline
- Hold until a position exits the top 2N of the ranking (a buffer band), not the top N.
  Swapping ranks 4 and 5 every week pays fees for noise.
- Maximum one entry per ticker per week; no re-entry into a stopped-out name for 5 sessions.

## What this skill must NOT do
- Do not size positions, set stops, or place orders.
- Do not override the gate because a story is compelling. Narrative is not a gate input.
- Do not add lookback windows or indicators mid-flight. Parameter changes go through the
  mandate and a human, otherwise you are curve-fitting in production.

## Provenance
Moskowitz, Ooi & Pedersen, "Time Series Momentum" (JFE 2012); Jegadeesh & Titman (1993);
Gray & Vogel, *Quantitative Momentum*; Antonacci, *Dual Momentum Investing*;
Clenow, *Stocks on the Move*; Carver, *Systematic Trading* (forecast scaling, buffering).
