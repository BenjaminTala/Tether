"""Market statistics from daily bars — deterministic context for the model and inputs for
stops/sizing. Pure functions; no network. All return None when there is not enough history:
callers must treat None as "no data" and fail closed, never substitute a guess.

Momentum score follows the classic 12-1 construction (Jegadeesh/Titman; Moskowitz-Ooi-Pedersen):
average of 3/6/12-month returns, excluding the most recent month to sidestep short-term reversal.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Sequence

from ibagent.broker.base import Bar

TRADING_DAYS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}


@dataclass(frozen=True)
class SymbolStats:
    symbol: str
    close: float
    atr: Optional[float]                 # Wilder ATR(n)
    atr_pct: Optional[float]             # atr / close
    ret_1m: Optional[float]
    ret_3m: Optional[float]
    ret_6m: Optional[float]
    ret_12m: Optional[float]
    momentum: Optional[float]            # mean(3m, 6m, 12m returns) each measured to 1m ago
    vol_20d_ann: Optional[float]         # annualized 20d realized vol
    ma20: Optional[float]                # 20d simple MA (anti-chasing reference)
    high_52w: Optional[float]
    pct_from_52w_high: Optional[float]   # (close - high) / high, <= 0
    above_50d: Optional[bool]
    above_200d: Optional[bool]
    bars: int


def atr(bars: Sequence[Bar], period: int = 14) -> Optional[float]:
    """Wilder-smoothed Average True Range. Needs period+1 bars."""
    if period < 1 or len(bars) < period + 1:
        return None
    trs: List[float] = []
    for prev, cur in zip(bars[:-1], bars[1:]):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    val = sum(trs[:period]) / period
    for tr in trs[period:]:
        val = (val * (period - 1) + tr) / period
    return round(val, 6)


def sma(closes: Sequence[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def trailing_return(closes: Sequence[float], days_back: int, skip_recent: int = 0) -> Optional[float]:
    """Return from `days_back` ago to `skip_recent` ago (both in trading days)."""
    if len(closes) <= days_back or days_back <= skip_recent:
        return None
    then, now = closes[-1 - days_back], closes[-1 - skip_recent]
    if then <= 0:
        return None
    return now / then - 1.0


def realized_vol_ann(closes: Sequence[float], period: int = 20) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    rets = [math.log(b / a) for a, b in zip(closes[-period - 1:-1], closes[-period:]) if a > 0 and b > 0]
    if len(rets) < period:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def momentum_12_1(closes: Sequence[float]) -> Optional[float]:
    """Mean of 3/6/12-month trailing returns, each excluding the most recent month."""
    parts = [trailing_return(closes, TRADING_DAYS[k], skip_recent=TRADING_DAYS["1m"])
             for k in ("3m", "6m", "12m")]
    have = [p for p in parts if p is not None]
    return sum(have) / len(have) if have else None


def symbol_stats(symbol: str, bars: Sequence[Bar], atr_period: int = 14) -> Optional[SymbolStats]:
    if not bars:
        return None
    closes = [b.close for b in bars]
    close = closes[-1]
    if close <= 0:
        return None
    a = atr(bars, atr_period)
    high_52 = max((b.high for b in bars[-TRADING_DAYS["12m"]:]), default=None) \
        if len(bars) >= TRADING_DAYS["6m"] else None
    ma50, ma200 = sma(closes, 50), sma(closes, 200)
    return SymbolStats(
        symbol=symbol, close=close, atr=a,
        atr_pct=round(a / close, 5) if a else None,
        ret_1m=trailing_return(closes, TRADING_DAYS["1m"]),
        ret_3m=trailing_return(closes, TRADING_DAYS["3m"]),
        ret_6m=trailing_return(closes, TRADING_DAYS["6m"]),
        ret_12m=trailing_return(closes, TRADING_DAYS["12m"]),
        momentum=momentum_12_1(closes),
        vol_20d_ann=realized_vol_ann(closes),
        ma20=round(m, 4) if (m := sma(closes, 20)) is not None else None,
        high_52w=high_52,
        pct_from_52w_high=round((close - high_52) / high_52, 5) if high_52 else None,
        above_50d=(close > ma50) if ma50 is not None else None,
        above_200d=(close > ma200) if ma200 is not None else None,
        bars=len(bars),
    )


def stats_table(bars_by_symbol: Dict[str, Sequence[Bar]], atr_period: int = 14) -> Dict[str, SymbolStats]:
    out: Dict[str, SymbolStats] = {}
    for sym, bars in sorted(bars_by_symbol.items()):
        s = symbol_stats(sym, bars, atr_period)
        if s is not None:
            out[sym] = s
    return out


def momentum_rank(table: Dict[str, SymbolStats]) -> List[str]:
    """Symbols with a momentum score, best first. Symbols without enough history are excluded."""
    scored = [(s.momentum, sym) for sym, s in table.items() if s.momentum is not None]
    return [sym for _, sym in sorted(scored, key=lambda t: (-t[0], t[1]))]


def table_as_dicts(table: Dict[str, SymbolStats]) -> Dict[str, dict]:
    return {sym: asdict(s) for sym, s in table.items()}
