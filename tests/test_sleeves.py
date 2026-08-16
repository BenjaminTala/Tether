from datetime import timedelta

import pytest

from ibagent.broker.base import Fill
from ibagent.sleeves import core_rebalance, evaluate_breakers, protective_actions
from tests.conftest import NOW, TODAY, make_book


def fill(symbol, side, qty, price, comm=0.35):
    return Fill(broker_order_id="1", client_tag="t", symbol=symbol, side=side,
                qty=qty, price=price, commission=comm, ts=NOW)


def enter(book, symbol, sleeve, qty, price, stop=None, time_stop_days=None):
    meta = {"stop_price": stop}
    if time_stop_days:
        meta["time_stop_trading_days"] = time_stop_days
    book.apply_fill(fill(symbol, "BUY", qty, price), sleeve, entry_meta=meta, counts_as_new=True)


# --------------------------------------------------------------------- protective actions

def test_spec_take_profit(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    enter(b, "TSLA", "spec", 1, 100, stop=90)
    acts = protective_actions(mandate, b, {"TSLA": 126}, {}, TODAY)   # +26% > 25% target
    assert [a.kind for a in acts] == ["take_profit"]
    assert acts[0].sell_qty == 1


def test_spec_time_stop(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    enter(b, "TSLA", "spec", 1, 100, stop=90, time_stop_days=10)
    assert protective_actions(mandate, b, {"TSLA": 105}, {}, TODAY) == []
    late = TODAY + timedelta(days=20)                                  # > 10 trading days
    acts = protective_actions(mandate, b, {"TSLA": 105}, {}, late)
    assert [a.kind for a in acts] == ["time_stop"]


def test_trend_partial_take_and_trail(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    enter(b, "QQQ", "trend", 2, 100, stop=92)                          # 1R = 8
    b.update_high_prices({"QQQ": 118})
    acts = protective_actions(mandate, b, {"QQQ": 118}, {"QQQ": 2.0}, TODAY)   # +2.25R
    kinds = {a.kind for a in acts}
    assert kinds == {"partial_take", "trail_stop"}
    partial = next(a for a in acts if a.kind == "partial_take")
    assert partial.sell_qty == pytest.approx(1.0)                      # half of 2
    trail = next(a for a in acts if a.kind == "trail_stop")
    assert trail.new_stop == pytest.approx(118 - 2.5 * 2.0)            # high - 2.5xATR = 113
    b.tighten_stop("QQQ", trail.new_stop)
    # trailing never loosens: with a lower high the trail is below the current stop -> no action
    again = protective_actions(mandate, b, {"QQQ": 114}, {"QQQ": 2.0}, TODAY)
    assert all(a.kind != "trail_stop" for a in again)


def test_no_price_no_action(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    enter(b, "QQQ", "trend", 2, 100, stop=92)
    assert protective_actions(mandate, b, {}, {}, TODAY) == []


# --------------------------------------------------------------------- circuit breakers

def test_total_drawdown_halts(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    b.hwm["total"] = 1200.0                                            # pot fell 1200 -> ~1000
    snap = b.equity({}, NOW)
    state = evaluate_breakers(mandate, b, snap)
    assert state.halt and any("total drawdown" in r for r in state.reasons)


def test_sleeve_drawdown_pauses(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    enter(b, "QQQ", "trend", 2, 100, stop=92)
    b.hwm["trend"] = 300.0                                             # trend value now 2x75=150
    snap = b.equity({"QQQ": 75}, NOW)
    state = evaluate_breakers(mandate, b, snap)
    assert "trend" in state.paused_sleeves and not state.halt


def test_daily_loss_pauses_entries(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    b.ensure_day(TODAY, 1100.0)                                        # -9% intraday
    b.day_start_equity = 1100.0
    snap = b.equity({}, NOW)
    state = evaluate_breakers(mandate, b, snap)
    assert state.pause_all_entries


def test_consecutive_spec_losers_pause(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    b.consecutive_spec_losers = 5
    state = evaluate_breakers(mandate, b, b.equity({}, NOW))
    assert "spec" in state.paused_sleeves


def test_quiet_book_no_breakers(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    snap = b.equity({}, NOW)
    b.update_hwm(snap)
    state = evaluate_breakers(mandate, b, snap)
    assert not state.any_tripped


# --------------------------------------------------------------------- core rebalance

def test_core_rebalance_from_all_cash(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    snap = b.equity({}, NOW)
    intents, sweep = core_rebalance(mandate, b, snap, {"VTI": 300, "SGOV": 100}, TODAY)
    assert sweep == 0.0
    by = {i.symbol: i for i in intents}
    # core = 50% of 1000: VTI 60% -> $300 buy, SGOV 40% -> $200 buy
    assert by["VTI"].side == "BUY" and by["VTI"].usd == pytest.approx(300, abs=1)
    assert by["SGOV"].side == "BUY" and by["SGOV"].usd == pytest.approx(200, abs=1)


def test_core_rebalance_inside_band_no_trades(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    b.apply_fill(fill("VTI", "BUY", 1, 295), "core", entry_meta={}, counts_as_new=False)
    b.apply_fill(fill("SGOV", "BUY", 2, 100), "core", entry_meta={}, counts_as_new=False)
    snap = b.equity({"VTI": 300, "SGOV": 100}, NOW)
    intents, _ = core_rebalance(mandate, b, snap, {"VTI": 300, "SGOV": 100}, TODAY)
    assert intents == []


def test_sweep_buys_core_even_inside_band(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    b.apply_fill(fill("VTI", "BUY", 1, 295), "core", entry_meta={}, counts_as_new=False)
    b.apply_fill(fill("SGOV", "BUY", 2, 100), "core", entry_meta={}, counts_as_new=False)
    b.spec_profit_since_sweep = 120.0                                  # sweep half = 60
    snap = b.equity({"VTI": 300, "SGOV": 100}, NOW)
    intents, sweep = core_rebalance(mandate, b, snap, {"VTI": 300, "SGOV": 100}, TODAY)
    assert sweep == pytest.approx(60.0)
    by = {i.symbol: i for i in intents}
    assert by["VTI"].side == "BUY" and by["VTI"].usd == pytest.approx(36, abs=4)    # 60% of sweep
    assert "SGOV" not in by                                            # 40% of 60 = 24 < min_order 25


def test_rebalance_capped_by_deployable_cash(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    b.request_withdrawal(900)                                          # only 100 deployable
    snap = b.equity({}, NOW)
    intents, _ = core_rebalance(mandate, b, snap, {"VTI": 300, "SGOV": 100}, TODAY)
    assert sum(i.usd for i in intents if i.side == "BUY") <= 100 + 1e-6
