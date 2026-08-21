from datetime import datetime, timedelta, timezone

import pytest

from ibagent.broker.base import Bar
from ibagent.data import (atr, momentum_12_1, momentum_rank, realized_vol_ann, sma, stats_table,
                          symbol_stats, trailing_return)


def make_bars(closes, start=datetime(2025, 1, 1, tzinfo=timezone.utc), spread=1.0):
    return [Bar(ts=start + timedelta(days=i), open=c, high=c + spread, low=c - spread,
                close=c, volume=1000) for i, c in enumerate(closes)]


def test_atr_constant_range():
    bars = make_bars([100.0] * 20, spread=1.0)          # TR = 2 every day
    assert atr(bars, 14) == pytest.approx(2.0)


def test_atr_needs_enough_bars():
    assert atr(make_bars([100.0] * 10), 14) is None


def test_trailing_return_and_skip():
    closes = list(range(100, 400))                       # rising linearly
    r = trailing_return(closes, 21)
    assert r == pytest.approx(closes[-1] / closes[-22] - 1)
    r_skip = trailing_return(closes, 63, skip_recent=21)
    assert r_skip == pytest.approx(closes[-22] / closes[-64] - 1)
    assert trailing_return([1, 2], 21) is None


def test_momentum_12_1_prefers_up_trends():
    up = [100 * (1.003 ** i) for i in range(300)]
    down = [100 * (0.997 ** i) for i in range(300)]
    assert momentum_12_1(up) > 0 > momentum_12_1(down)


def test_realized_vol_flat_is_zero():
    assert realized_vol_ann([100.0] * 30) == pytest.approx(0.0)
    assert realized_vol_ann([100.0] * 10) is None


def test_symbol_stats_and_rank():
    up = make_bars([100 * (1.002 ** i) for i in range(300)])
    down = make_bars([100 * (0.999 ** i) for i in range(300)])
    table = stats_table({"UP": up, "DOWN": down})
    assert momentum_rank(table) == ["UP", "DOWN"]
    s = table["UP"]
    assert s.above_200d and s.atr and s.atr_pct and s.high_52w
    assert s.pct_from_52w_high <= 0


def test_symbol_stats_sparse_history_fails_closed():
    s = symbol_stats("X", make_bars([100.0] * 5))
    assert s is not None and s.momentum is None and s.atr is None and s.high_52w is None
    assert symbol_stats("X", []) is None


def test_sma():
    assert sma([1, 2, 3, 4], 2) == 3.5
    assert sma([1], 2) is None


def test_intraday_fields_only_when_last_bar_is_today():
    from datetime import date
    bars = make_bars([100.0, 102.0])
    bars[-1] = Bar(ts=bars[-1].ts, open=101.0, high=103.0, low=100.5, close=102.0, volume=1000)
    today = bars[-1].ts.date()
    s = symbol_stats("X", bars, today=today)
    assert s.day_open == 101.0
    assert s.day_change_from_open == pytest.approx(102.0 / 101.0 - 1, abs=1e-4)
    assert s.day_change == pytest.approx(0.02, abs=1e-4)
    assert s.day_range_pos == pytest.approx((102.0 - 100.5) / (103.0 - 100.5), abs=1e-3)
    # cached/stale history (last bar not today) -> all intraday fields None
    stale = symbol_stats("X", bars, today=date(2030, 1, 1))
    assert stale.day_open is None and stale.day_change is None and stale.day_range_pos is None
    # no `today` context -> None as well
    assert symbol_stats("X", bars).day_open is None
