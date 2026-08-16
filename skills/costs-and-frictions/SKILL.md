---
name: costs-and-frictions
description: Account for commissions, spreads, slippage, settlement and tax drag before approving a trade. Use whenever a trade is proposed at a small account size, and in every monthly review. At $1000 of capital, costs are a first-order strategy input, not a footnote.
---

# Costs & Frictions

## Principle
Gross edge is a hypothesis; net edge is the only thing that reaches the account. A strategy
with a 0.4% average edge per trade and 0.3% round-trip costs has lost three quarters of itself
before it starts. At small size, cost control IS strategy.

## Cost stack per round trip
1. **Commission** - fixed or per-share, whichever the plan charges. On a $40 position a $0.35
   minimum is 0.9% one way, 1.8% round trip. That alone kills most short-horizon ideas.
2. **Spread** - half the bid/ask on entry and again on exit. Wide-spread instruments are
   structurally untradeable in small size.
3. **Slippage** - assume you get the worse side of the quote on marketable orders. Never model
   fills at the mid.
4. **Tax drag** - short holding periods generally mean the least favourable tax treatment.
   Turnover is taxed; buy-and-hold defers. Jurisdiction-specific: read it from the mandate,
   never assume.

## Gate applied to every proposed trade
```
est_cost_round_trip = 2*commission + spread_pct*notional + slippage_pct*notional
if est_cost_round_trip > 0.005 * notional:      -> reject: cost_gate
if notional < mandate.min_notional:             -> reject: min_size
if expected_move_to_target < 3 * est_cost_pct:  -> reject: insufficient_edge
```

## Structural rules for a small cash account
- Prefer few, larger, longer-held positions over many small short ones. Costs scale with
  trade count; edge does not.
- Fractional shares make sizing precise but do not reduce spread or commission - do not let
  precision tempt you into more trades.
- **Settlement**: in a cash account, proceeds are unavailable until settled. Track settled
  cash, not buying power. Trading unsettled funds is a compliance problem, not a clever trick.
- Turnover budget: cap trades per month in the mandate and treat it as a hard resource.
  Spending it early means sitting out later.
- Instruments with low expense ratios for the core sleeve; a 0.5% annual fee is a large
  fraction of a realistic return at this size.

## Monthly report line
Report total costs as a percentage of both equity and gross P&L. If costs exceed 25% of gross
P&L, the trading frequency is wrong and the mandate should be tightened.

## Provenance
Cost/turnover realism: Carver, *Systematic Trading*; Bogle, *Common Sense on Mutual Funds*
(cost drag on long-run returns); Chan, *Algorithmic Trading* (transaction cost modelling in
backtests); Barber & Odean, "Trading Is Hazardous to Your Wealth" (turnover destroys retail returns).
