"""Commission and fee estimator (IBKR Pro, US stocks/ETFs). Conservative, not exact.

  tiered: max(0.35, 0.0035/sh) + exchange (remove liquidity ~0.0030/sh) + clearing 0.0002/sh, cap 1% of value
  fixed:  max(1.00, 0.0050/sh), cap 1% of value (exchange + clearing included)
  lite:   0
  sells (all plans): FINRA TAF 0.000166/sh (max 8.30). SEC Section 31 fee treated as 0 (rate is
  reviewed by the SEC each fiscal year; adjust SEC_FEE_RATE if it becomes non-zero again).

Used by SimBroker for realistic fills and by risk.py for capital.max_fee_pct_per_trade.
"""
from __future__ import annotations

from typing import Literal

from ibagent.common import Side

CommissionModel = Literal["tiered", "fixed", "lite"]

TIERED_PER_SHARE, TIERED_MIN = 0.0035, 0.35
TIERED_PASS_THROUGH_PER_SHARE = 0.0032          # exchange remove-liquidity + clearing
FIXED_PER_SHARE, FIXED_MIN = 0.0050, 1.00
MAX_PCT_OF_VALUE = 0.01
FINRA_TAF_PER_SHARE, FINRA_TAF_MAX = 0.000166, 8.30
SEC_FEE_RATE = 0.0                              # per $ of sale proceeds


def estimate_commission(model: CommissionModel, qty: float, price: float, side: Side) -> float:
    """Total estimated cost (USD) for one order. Raises on non-positive qty/price."""
    if qty <= 0 or price <= 0:
        raise ValueError("qty and price must be positive")
    value = qty * price
    if model == "tiered":
        comm = max(TIERED_MIN, min(TIERED_PER_SHARE * qty, MAX_PCT_OF_VALUE * value))
        comm += TIERED_PASS_THROUGH_PER_SHARE * qty
    elif model == "fixed":
        comm = max(FIXED_MIN, min(FIXED_PER_SHARE * qty, MAX_PCT_OF_VALUE * value))
    elif model == "lite":
        comm = 0.0
    else:
        raise ValueError(f"unknown commission model {model}")
    if side == "SELL":
        comm += min(FINRA_TAF_PER_SHARE * qty, FINRA_TAF_MAX) + SEC_FEE_RATE * value
    return round(comm, 2)


def fee_pct(model: CommissionModel, qty: float, price: float, side: Side) -> float:
    """Estimated cost as a percent of order notional."""
    return 100.0 * estimate_commission(model, qty, price, side) / (qty * price)
