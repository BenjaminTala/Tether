"""Backtester for the DETERMINISTIC strategy skeletons (no LLM anywhere in the loop).

Honesty contract, printed with every result:
  * Only mechanical rules are tested (momentum rotation, ATR stops, allocations). The AI's
    judgment CANNOT be backtested — the model's training data knows how history played out,
    so any "AI backtest" is look-ahead contaminated by construction.
  * The universe is today's whitelist -> survivorship bias: names that imploded before
    making the list are invisible. Results are therefore OPTIMISTIC upper bounds.
  * Fills at the daily close with slippage; stops fill at min(stop, low-open gap) like the
    live sim. Commissions per the mandate's fee model.

Strategies mirror fleet variants so the forward test (shadows) and the backward test agree
on definitions:
  core_only   60/40 VTI/SGOV, monthly rebalance                       (~ the core sleeve)
  momentum    top-N by 12-1 momentum, monthly rotation, ATR trail     (~ trend sleeve/bold)
  swing       same but tight stops (2 ATR) and weekly rotation        (~ swing)
  spy         buy-and-hold SPY                                        (benchmark)
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ibagent.broker.base import Bar
from ibagent.data import atr as calc_atr, momentum_12_1
from ibagent.fees import CommissionModel, estimate_commission

HISTORY_DIR = Path("data") / "history"
SLIPPAGE = 0.0005
MIN_HISTORY = 260                       # a strategy may not trade until a year of data exists


# --------------------------------------------------------------------------- history cache

def save_history(symbol: str, bars: Sequence[Bar], directory: Path = HISTORY_DIR) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    rows = [[b.ts.date().isoformat(), b.open, b.high, b.low, b.close, b.volume] for b in bars]
    (directory / f"{symbol}.json").write_text(json.dumps(rows), encoding="utf-8")

def load_history(symbol: str, directory: Path = HISTORY_DIR) -> Optional[List[Bar]]:
    p = directory / f"{symbol}.json"
    if not p.exists():
        return None
    out = []
    for d, o, h, l, c, v in json.loads(p.read_text(encoding="utf-8")):
        ts = datetime.fromisoformat(d + "T21:00:00+00:00")
        out.append(Bar(ts=ts, open=o, high=h, low=l, close=c, volume=v))
    return out


# --------------------------------------------------------------------------- the engine

@dataclass
class BTPosition:
    qty: float
    entry: float
    stop: Optional[float] = None
    high: float = 0.0

@dataclass
class BTResult:
    name: str
    start: date
    end: date
    initial: float
    final: float
    cagr: float
    max_drawdown: float
    sharpe: float
    trades: int
    fees: float
    equity_curve: List[Tuple[date, float]] = field(default_factory=list)

# A strategy sees (history so far per symbol, current positions) on REBALANCE days and
# returns target weights {symbol: weight}. Stops are handled by the engine daily.
Strategy = Callable[[Dict[str, List[Bar]], Dict[str, BTPosition]], Dict[str, float]]


def run_backtest(name: str, bars_by_symbol: Dict[str, List[Bar]], strategy: Strategy,
                 rebalance: str = "monthly", initial: float = 10_000.0,
                 commission: CommissionModel = "fixed", trail_atr: Optional[float] = None,
                 whole_shares: bool = True) -> BTResult:
    dates = sorted({b.ts.date() for bars in bars_by_symbol.values() for b in bars})
    series: Dict[str, Dict[date, Bar]] = {
        s: {b.ts.date(): b for b in bars} for s, bars in bars_by_symbol.items()}
    hist: Dict[str, List[Bar]] = {s: [] for s in bars_by_symbol}

    cash, fees, trades = initial, 0.0, 0
    positions: Dict[str, BTPosition] = {}
    curve: List[Tuple[date, float]] = []
    last_period = None

    def mark(d: date) -> float:
        total = cash
        for s, p in positions.items():
            bar = series[s].get(d)
            total += p.qty * (bar.close if bar else hist[s][-1].close if hist[s] else p.entry)
        return total

    def sell(sym: str, price: float) -> None:
        nonlocal cash, fees, trades
        p = positions.pop(sym)
        fee = estimate_commission(commission, p.qty, price, "SELL")
        cash += p.qty * price * (1 - SLIPPAGE) - fee
        fees += fee
        trades += 1

    def buy(sym: str, usd: float, price: float, stop: Optional[float]) -> None:
        nonlocal cash, fees, trades
        px = price * (1 + SLIPPAGE)
        qty = int(usd / px) if whole_shares else round(usd / px, 4)
        if qty <= 0:
            return
        fee = estimate_commission(commission, qty, px, "BUY")
        if qty * px + fee > cash:
            qty = int((cash - fee) / px) if whole_shares else max(0.0, (cash - fee) / px)
            if qty <= 0:
                return
        cash -= qty * px + fee
        fees += fee
        trades += 1
        positions[sym] = BTPosition(qty=qty, entry=px, stop=stop, high=price)

    for d in dates:
        for s, by_date in series.items():
            if d in by_date:
                hist[s].append(by_date[d])
        if any(len(h) < MIN_HISTORY for h in hist.values() if h) or not any(hist.values()):
            curve.append((d, mark(d)))
            continue

        # 1. stops first (gap-aware: fill at the worse of stop or open)
        for s in list(positions):
            bar = series[s].get(d)
            p = positions[s]
            if bar is None or p.stop is None:
                continue
            if bar.low <= p.stop:
                sell(s, min(p.stop, bar.open) if bar.open < p.stop else p.stop)
            else:
                p.high = max(p.high, bar.high)
                if trail_atr:
                    a = calc_atr(hist[s][-15:], 14)
                    if a:
                        p.stop = max(p.stop, p.high - trail_atr * a)

        # 2. rebalance on period change
        period = (d.year, d.month) if rebalance == "monthly" else (d.year, d.isocalendar()[1])
        if period != last_period:
            last_period = period
            targets = strategy(hist, positions)
            for s in [s for s in positions if targets.get(s, 0) <= 0]:
                bar = series[s].get(d)
                if bar:
                    sell(s, bar.close)
            equity = mark(d)
            for s, w in targets.items():
                if w <= 0 or s in positions:
                    continue
                bar = series[s].get(d)
                if bar is None:
                    continue
                a = calc_atr(hist[s][-15:], 14)
                stop = round(bar.close - 2.5 * a, 4) if (a and trail_atr) else None
                buy(s, equity * w, bar.close, stop)
        curve.append((d, mark(d)))

    # metrics
    eq = [v for _, v in curve]
    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]
    years = max((curve[-1][0] - curve[0][0]).days / 365.25, 1e-9)
    cagr = (eq[-1] / initial) ** (1 / years) - 1 if eq[-1] > 0 else -1.0
    peak, maxdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0.0)
    mean = sum(rets) / len(rets) if rets else 0.0
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1) if len(rets) > 1 else 0.0
    sharpe = (mean / math.sqrt(var) * math.sqrt(252)) if var > 0 else 0.0
    return BTResult(name=name, start=curve[0][0], end=curve[-1][0], initial=initial,
                    final=round(eq[-1], 2), cagr=cagr, max_drawdown=maxdd, sharpe=sharpe,
                    trades=trades, fees=round(fees, 2), equity_curve=curve)


# --------------------------------------------------------------------------- strategies

def strat_spy(hist, positions):
    return {"SPY": 0.99}

def strat_core_only(hist, positions):
    return {"VTI": 0.60, "SGOV": 0.39}

def make_momentum(universe: Sequence[str], top_n: int = 3, invest: float = 0.90,
                  park: str = "SGOV"):
    def strat(hist, positions):
        scored = []
        for s in universe:
            closes = [b.close for b in hist.get(s, [])]
            m = momentum_12_1(closes)
            if m is not None and m > 0 and len(closes) >= 200 \
                    and closes[-1] > sum(closes[-200:]) / 200:
                scored.append((m, s))
        picks = [s for _, s in sorted(scored, reverse=True)[:top_n]]
        w = {s: invest / top_n for s in picks}
        w[park] = max(0.0, 0.99 - sum(w.values()))
        return w
    return strat
