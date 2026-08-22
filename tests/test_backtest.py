"""Backtester correctness on synthetic price paths with known outcomes."""
from datetime import datetime, timedelta, timezone

import pytest

from ibagent.backtest import (BTResult, load_history, make_momentum, run_backtest,
                              save_history, strat_spy)
from ibagent.broker.base import Bar


def daily_bars(prices, start=datetime(2023, 1, 2, 21, tzinfo=timezone.utc), spread=0.5):
    out, d = [], start
    for p in prices:
        if d.weekday() < 5:
            out.append(Bar(ts=d, open=p, high=p + spread, low=p - spread, close=p, volume=1e6))
        d += timedelta(days=1)
    return out


def test_buy_and_hold_tracks_the_market():
    n = 700
    prices = [100 * (1.0004 ** i) for i in range(n)]           # ~10%/yr steady grind
    r = run_backtest("spy", {"SPY": daily_bars(prices)}, strat_spy)
    assert r.trades == 1                                        # one buy, never sold
    assert r.final > r.initial                                  # made money
    assert 0.05 < r.cagr < 0.15
    assert r.max_drawdown < 0.02                                # steady path, tiny dd


def test_stop_cuts_a_crash():
    n = 700
    prices = [100.0] * 400 + [100 * (0.98 ** i) for i in range(n - 400)]   # then a -45% slide
    universe = ["AAA"]
    r = run_backtest("mom", {"AAA": daily_bars(prices), "SGOV": daily_bars([100.0] * n)},
                     make_momentum(universe, 1), rebalance="monthly", trail_atr=2.5)
    # momentum never triggers (flat then falling) OR the stop exits early: either way the
    # strategy must not ride the crash to the bottom
    assert r.max_drawdown < 0.20
    assert r.final > r.initial * 0.85


def test_momentum_picks_the_riser():
    n = 700
    up = daily_bars([100 * (1.0012 ** i) for i in range(n)])    # strong riser
    flat = daily_bars([100.0] * n)
    r = run_backtest("mom", {"UP": up, "FLAT": flat, "SGOV": daily_bars([100.0] * n)},
                     make_momentum(["UP", "FLAT"], 1), rebalance="monthly", trail_atr=2.5)
    assert r.final > r.initial * 1.15                           # it rode UP, not FLAT


def test_fees_and_turnover_accounted():
    n = 700
    up = daily_bars([100 * (1.0012 ** i) for i in range(n)])
    r_monthly = run_backtest("m", {"UP": up, "SGOV": daily_bars([100.0] * n)},
                             make_momentum(["UP"], 1), rebalance="monthly", trail_atr=2.5)
    assert r_monthly.fees >= 1.0 and r_monthly.trades >= 1


def test_history_cache_roundtrip(tmp_path):
    bars = daily_bars([100, 101, 102])
    save_history("XYZ", bars, directory=tmp_path)
    loaded = load_history("XYZ", directory=tmp_path)
    assert len(loaded) == len(bars)
    assert loaded[0].close == 100 and loaded[-1].close == 102
    assert load_history("NOPE", directory=tmp_path) is None
