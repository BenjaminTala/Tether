from datetime import datetime, timedelta, timezone

import pytest

from ibagent.broker.base import Fill
from ibagent.risk import plan_orders
from ibagent.schemas import Decision, PositionIntent, StopUpdate
from tests.conftest import NOW, TODAY, make_book, make_quote

THESIS = "momentum breakout above range"
INVALID = "close below the 50-day"


def intent(symbol, sleeve, weight, stop=None, target=None):
    return PositionIntent(symbol=symbol, sleeve=sleeve, target_weight=weight, thesis=THESIS,
                          invalidation=INVALID, stop_price=stop, target_price=target,
                          confidence=0.6, horizon_days=30)


def rebalance(*positions, mult=1.0, stops=()):
    return Decision(run_type="weekly", action="rebalance", market_regime="neutral",
                    risk_multiplier=mult, positions=list(positions), stop_updates=list(stops),
                    notes_for_human="test")


def no_change(*stops):
    return Decision(run_type="daily", action="no_change", market_regime="neutral",
                    risk_multiplier=1.0, stop_updates=list(stops), notes_for_human="test")


def fill(symbol, side, qty, price, comm=0.35):
    return Fill(broker_order_id="1", client_tag="t", symbol=symbol, side=side,
                qty=qty, price=price, commission=comm, ts=NOW)


def enter(book, symbol, sleeve, qty, price, stop=None):
    book.apply_fill(fill(symbol, "BUY", qty, price), sleeve,
                    entry_meta={"stop_price": stop, "stop_order_tag": f"stp-{symbol}"}, counts_as_new=True)


# --------------------------------------------------------------------- global refusals

def test_hold_on_kill_frozen_halted(mandate, tmp_path):
    b = make_book(tmp_path)
    d = rebalance(intent("QQQ", "trend", 0.12, stop=92))
    q = {"QQQ": make_quote("QQQ", 100)}
    assert plan_orders(mandate, b, q, {}, d, NOW, kill_switch=True).hold
    b.freeze("mismatch")
    assert plan_orders(mandate, b, q, {}, d, NOW).hold
    b.unfreeze()
    b.halt("drawdown")
    assert plan_orders(mandate, b, q, {}, d, NOW).hold


def test_hold_outside_trade_window(mandate, tmp_path):
    b = make_book(tmp_path)
    d = rebalance(intent("QQQ", "trend", 0.12, stop=92))
    at_open = datetime(2026, 8, 12, 13, 40, tzinfo=timezone.utc)       # 9:40 ET, inside buffer
    plan = plan_orders(mandate, b, {"QQQ": make_quote("QQQ", 100, ts=at_open)}, {}, d, at_open)
    assert plan.hold and "RTH" in plan.hold_reason


def test_hold_on_stale_held_quote(mandate, tmp_path):
    b = make_book(tmp_path)
    enter(b, "QQQ", "trend", 1, 100, stop=92)
    stale = make_quote("QQQ", 100, ts=NOW - timedelta(hours=2))
    plan = plan_orders(mandate, b, {"QQQ": stale}, {}, no_change(), NOW)
    assert plan.hold and "stale" in plan.hold_reason


def test_hold_when_held_symbol_unpriced(mandate, tmp_path):
    b = make_book(tmp_path)
    enter(b, "QQQ", "trend", 1, 100, stop=92)
    plan = plan_orders(mandate, b, {}, {}, no_change(), NOW)
    assert plan.hold and "mark" in plan.hold_reason


# --------------------------------------------------------------------- entries

def test_basic_entry_sized_by_risk_with_stop(mandate, tmp_path):
    b = make_book(tmp_path)
    q = make_quote("QQQ", 100)
    plan = plan_orders(mandate, b, {"QQQ": q}, {}, rebalance(intent("QQQ", "trend", 0.12, stop=92)), NOW)
    assert not plan.hold and len(plan.orders) == 1
    o = plan.orders[0]
    assert o.req.side == "BUY" and o.counts_as_new and o.intent == "entry"
    # size = min(weight cap $120 / price, risk $10 / $8 stop distance) = min(1.2, 1.25) = 1.2
    assert o.req.qty == pytest.approx(1.2)
    assert o.req.limit_price == pytest.approx(round(q.ask * 1.0015, 2))
    assert o.entry_meta["stop_price"] == pytest.approx(92)
    [s] = plan.stop_instructions
    assert s.symbol == "QQQ" and s.stop_price == pytest.approx(92) and s.qty == pytest.approx(1.2)


def test_whitelist_and_never_list_rejected(mandate, tmp_path):
    b = make_book(tmp_path)
    d = rebalance(intent("FAKE", "trend", 0.1, stop=92), intent("TQQQ", "trend", 0.1, stop=92))
    plan = plan_orders(mandate, b, {"FAKE": make_quote("FAKE", 100), "TQQQ": make_quote("TQQQ", 100)},
                       {}, d, NOW)
    assert plan.orders == []
    assert {r.symbol for r in plan.rejections} == {"FAKE", "TQQQ"}


def test_stop_out_of_bounds_falls_back_to_atr_else_reject(mandate, tmp_path):
    b = make_book(tmp_path)
    q = {"NVDA": make_quote("NVDA", 100)}
    tight = rebalance(intent("NVDA", "trend", 0.12, stop=99.5))        # 0.5% < 3% min distance
    plan = plan_orders(mandate, b, q, {"NVDA": 2.0}, tight, NOW)
    [o] = plan.orders
    assert o.entry_meta["stop_price"] == pytest.approx(95.0)           # 100 - 2.5x2.0 ATR
    plan2 = plan_orders(mandate, b, q, {}, tight, NOW)                 # no ATR -> fail closed
    assert plan2.orders == [] and "no valid stop" in plan2.rejections[0].reason


def test_no_averaging_down(mandate, tmp_path):
    b = make_book(tmp_path)
    enter(b, "QQQ", "trend", 1, 100, stop=92)                          # avg_cost ~100.35
    plan = plan_orders(mandate, b, {"QQQ": make_quote("QQQ", 95)}, {},
                       rebalance(intent("QQQ", "trend", 0.12, stop=88)), NOW)
    assert plan.orders == []
    assert "averaging down" in plan.rejections[0].reason


def test_cooldown_blocks_reentry(mandate, tmp_path):
    b = make_book(tmp_path)
    b.record_stop_out("QQQ", TODAY, 5)
    plan = plan_orders(mandate, b, {"QQQ": make_quote("QQQ", 100)}, {},
                       rebalance(intent("QQQ", "trend", 0.12, stop=92)), NOW)
    assert plan.orders == [] and "cooldown" in plan.rejections[0].reason


def test_weekly_new_position_cap(mandate, tmp_path):
    b = make_book(tmp_path)
    b.week_new_positions = 3
    plan = plan_orders(mandate, b, {"QQQ": make_quote("QQQ", 100)}, {},
                       rebalance(intent("QQQ", "trend", 0.12, stop=92)), NOW)
    assert plan.orders == [] and "new-position cap" in plan.rejections[0].reason


def test_weekly_turnover_cap(mandate, tmp_path):
    b = make_book(tmp_path)
    b.week_turnover_usd = 495.0                                        # budget: 500 - 495 = 5
    plan = plan_orders(mandate, b, {"QQQ": make_quote("QQQ", 100)}, {},
                       rebalance(intent("QQQ", "trend", 0.12, stop=92)), NOW)
    assert plan.orders == [] and "turnover" in plan.rejections[0].reason


def test_settled_cash_constraint(mandate, tmp_path):
    b = make_book(tmp_path)
    b.request_withdrawal(950)                                          # 50 deployable < 100 min position
    plan = plan_orders(mandate, b, {"QQQ": make_quote("QQQ", 100)}, {},
                       rebalance(intent("QQQ", "trend", 0.12, stop=92)), NOW)
    assert plan.orders == [] and "settled cash" in plan.rejections[0].reason


def test_open_risk_cap(mandate, tmp_path):
    b = make_book(tmp_path)
    enter(b, "NVDA", "trend", 1, 100, stop=55)                         # open risk = 45 of max 50
    d = rebalance(intent("NVDA", "trend", 0.045, stop=55), intent("QQQ", "trend", 0.12, stop=92))
    plan = plan_orders(mandate, b, {"NVDA": make_quote("NVDA", 100), "QQQ": make_quote("QQQ", 100)},
                       {}, d, NOW)
    assert all(o.req.symbol != "QQQ" for o in plan.orders)             # would add ~9.6 risk > 50 cap
    assert any("open-risk" in r.reason for r in plan.rejections)


def test_sleeve_paused_blocks_entries(mandate, tmp_path):
    b = make_book(tmp_path)
    b.pause_sleeve("spec", TODAY + timedelta(days=30))
    plan = plan_orders(mandate, b, {"TSLA": make_quote("TSLA", 100)}, {},
                       rebalance(intent("TSLA", "spec", 0.06, stop=90)), NOW)
    assert plan.orders == [] and "paused" in plan.rejections[0].reason


def test_max_positions_per_sleeve_at_current_equity(mandate, tmp_path):
    b = make_book(tmp_path, 1000)                                      # trend: min(4, 300/100) = 3
    for sym in ("SPY", "QQQ", "IWM"):
        enter(b, sym, "trend", 1, 60, stop=55)
    b.week_new_positions = 0                                           # isolate the per-sleeve cap
    quotes = {s: make_quote(s, 60) for s in ("SPY", "QQQ", "IWM")}
    quotes["DIA"] = make_quote("DIA", 100)
    d = rebalance(intent("SPY", "trend", 0.06, stop=55), intent("QQQ", "trend", 0.06, stop=55),
                  intent("IWM", "trend", 0.06, stop=55), intent("DIA", "trend", 0.1, stop=92))
    plan = plan_orders(mandate, b, quotes, {}, d, NOW)
    assert all(o.req.symbol != "DIA" for o in plan.orders)
    assert any("max positions" in r.reason for r in plan.rejections)


def test_operating_floor_blocks_entries(mandate, tmp_path):
    b = make_book(tmp_path, 300)                                       # below 400 floor
    plan = plan_orders(mandate, b, {"QQQ": make_quote("QQQ", 100)}, {},
                       rebalance(intent("QQQ", "trend", 0.12, stop=92)), NOW)
    assert plan.orders == [] and "operating floor" in plan.rejections[0].reason


# --------------------------------------------------------------------- exits / trims

def test_exit_positions_not_in_target_and_exits_first(mandate, tmp_path):
    b = make_book(tmp_path, 2000)
    enter(b, "SPY", "trend", 1, 200, stop=185)
    quotes = {"SPY": make_quote("SPY", 210), "QQQ": make_quote("QQQ", 100)}
    plan = plan_orders(mandate, b, quotes, {}, rebalance(intent("QQQ", "trend", 0.10, stop=92)), NOW)
    sides = [o.req.side for o in plan.orders]
    assert sides == ["SELL", "BUY"]
    sell = plan.orders[0]
    assert sell.req.symbol == "SPY" and sell.req.qty == 1 and sell.intent == "exit"


def test_risk_multiplier_zero_trims_everything(mandate, tmp_path):
    b = make_book(tmp_path)
    enter(b, "QQQ", "trend", 1, 100, stop=92)
    plan = plan_orders(mandate, b, {"QQQ": make_quote("QQQ", 110)}, {},
                       rebalance(intent("QQQ", "trend", 0.12, stop=95), mult=0.0), NOW)
    [o] = plan.orders
    assert o.req.side == "SELL" and o.req.qty == pytest.approx(1) and o.intent == "trim"


def test_sleeve_migration_rejected(mandate, tmp_path):
    b = make_book(tmp_path)
    enter(b, "AAPL", "trend", 1, 100, stop=92)
    plan = plan_orders(mandate, b, {"AAPL": make_quote("AAPL", 110)}, {},
                       rebalance(intent("AAPL", "spec", 0.06, stop=100)), NOW)
    assert any("migration" in r.reason for r in plan.rejections)
    # not in the sanitized target book -> exited
    assert [o.intent for o in plan.orders] == ["exit"]


# --------------------------------------------------------------------- stop updates

def test_stop_updates_tighten_only(mandate, tmp_path):
    b = make_book(tmp_path)
    enter(b, "QQQ", "trend", 1, 100, stop=92)
    d = no_change(StopUpdate(symbol="QQQ", stop_price=95, reason="lock gains"),
                  StopUpdate(symbol="MSFT", stop_price=90, reason="not held"))
    plan = plan_orders(mandate, b, {"QQQ": make_quote("QQQ", 110)}, {}, d, NOW)
    [s] = plan.stop_instructions
    assert s.symbol == "QQQ" and s.stop_price == 95 and s.replaces_tag == "stp-QQQ"
    assert plan.rejections[0].symbol == "MSFT"


def test_stop_update_widening_rejected(mandate, tmp_path):
    b = make_book(tmp_path)
    enter(b, "QQQ", "trend", 1, 100, stop=92)
    d = no_change(StopUpdate(symbol="QQQ", stop_price=90, reason="give it room"))
    plan = plan_orders(mandate, b, {"QQQ": make_quote("QQQ", 100)}, {}, d, NOW)
    assert plan.stop_instructions == []
    assert "does not tighten" in plan.rejections[0].reason


def test_stop_update_above_market_rejected(mandate, tmp_path):
    b = make_book(tmp_path)
    enter(b, "QQQ", "trend", 1, 100, stop=92)
    d = no_change(StopUpdate(symbol="QQQ", stop_price=111, reason="oops"))
    plan = plan_orders(mandate, b, {"QQQ": make_quote("QQQ", 110)}, {}, d, NOW)
    assert plan.stop_instructions == []
    assert "instantly" in plan.rejections[0].reason


def test_fee_cap_rejects_dust_after_sizing(md, tmp_path):
    from ibagent.config import mandate_from_dict
    md["capital"]["commission_model"] = "fixed"                        # $1 min per order
    md["capital"]["max_fee_pct_per_trade"] = 0.5
    mandate = mandate_from_dict(md)
    b = make_book(tmp_path)
    plan = plan_orders(mandate, b, {"QQQ": make_quote("QQQ", 100)}, {},
                       rebalance(intent("QQQ", "trend", 0.12, stop=92)), NOW)
    # $120 order at $1 fixed = 0.83% > 0.5% cap
    assert plan.orders == [] and "fee" in plan.rejections[0].reason
