---
name: position-sizing
description: Convert a trade idea into a position size using risk-based sizing, volatility scaling and portfolio heat limits. Use for every proposed entry, before any order is generated. This skill has veto power - if the size comes out below the minimum viable, the trade is skipped.
---

# Position Sizing & Portfolio Risk

## Principle
Survival is the only compounding requirement. Sizing, not selection, decides whether a
losing streak is an inconvenience or the end. Risk a fixed small fraction of equity per
trade, scaled by the instrument's volatility so that every position risks the same amount
regardless of how jumpy it is.

## Core formula
```
risk_budget      = equity * risk_pct              # e.g. 1.0% trend, 0.5% speculative
stop_distance    = k * ATR(20)                    # k from mandate, default 2.0
shares           = risk_budget / stop_distance     # fractional shares permitted
notional         = shares * price
```
Then clamp: `notional <= equity * max_position_pct` (default 15%). If the volatility-derived
size exceeds the concentration cap, the cap wins.

## Portfolio heat
- **Open risk** = sum over open positions of `(entry - current_stop) * shares`.
- Hard ceiling: total open risk <= 5% of equity. A new trade that breaches it is not taken,
  no matter how good it looks. Reduce elsewhere first or skip.
- **Correlation heat**: positions with 60-day correlation > 0.7 count as one cluster; a
  cluster may not exceed 2x the single-trade risk budget.
- Sleeve ceilings from the mandate (core / trend / speculative) apply on top of all of this.

## Scaling with equity
- Sizing is always computed off *current* equity, so wins grow size and losses shrink it
  automatically. Never size off peak equity or off the original deposit.
- After a drawdown of 10% from the high-water mark, halve `risk_pct` until a new high is made.

## Kelly and why we sit far below it
Full Kelly maximises long-run growth only if the edge estimate is exact - and yours is not.
It also produces drawdowns most humans and all small accounts cannot survive. Use a small
fixed fraction (1% risk per trade is roughly quarter-Kelly-ish territory for a modest edge)
and treat any suggestion to size up because of a hot streak as a bug.

## Prohibited sizing modes
Published sizing skills commonly offer a **Kelly criterion mode** driven by the trader's own
win rate and average win/loss. This system does not use it. Kelly requires an accurate edge
estimate; with fewer than ~30 closed trades per sleeve the inputs are noise, and the output is
a confident-looking recommendation to size up after a lucky streak. Fixed fractional with
volatility scaling only.

Equally prohibited: inferring an entry or stop price from "technical analysis" when a price is
not available. If the data layer did not return a price, the trade does not get sized. Some
sizing tools will happily suggest levels from a ticker alone — that convenience is a
hallucination surface in an automated path.

## Minimum viable trade
At small account sizes a position can be too small to be worth its costs. If
`notional < mandate.min_notional` (default $25) or expected round-trip cost exceeds 0.5% of
notional, skip the trade. See `costs-and-frictions`.

## Output
`{ticker, shares, notional, stop_price, risk_dollars, pct_of_equity, heat_after, decision}`
where decision is one of `size_ok | reduced_to_cap | rejected_heat | rejected_min_size`.

## Provenance
Van Tharp, *Trade Your Way to Financial Freedom* (position sizing, R-multiples, expectancy);
Ralph Vince, *The Mathematics of Money Management*; Turtle rules via Faith, *Way of the Turtle*
(N/ATR volatility units); Carver, *Systematic Trading* (volatility targeting);
Thorp/Kelly literature for why fractional Kelly, not full.

## Fail-closed
If equity, ATR, price, or current open risk cannot be read, the sizing decision is
`rejected_incomplete_data`. Never substitute a default, a last-known value, or an estimate.
