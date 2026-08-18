from datetime import timedelta

import pytest

from ibagent.alerts import Alerter
from ibagent.broker.sim import SimBroker, SimConfig
from ibagent.execution import Executor
from ibagent.journal import Journal
from ibagent.risk import plan_orders
from ibagent.sleeves import ProtectiveAction, RebalanceIntent
from ibagent.schemas import Decision, PositionIntent
from tests.conftest import NOW, TODAY, make_book, make_quote


def make_exec(mandate, tmp_path, cash=1000.0, sim_cash=None):
    broker = SimBroker(SimConfig(initial_cash=sim_cash if sim_cash is not None else cash))
    broker.connect()
    broker.set_time(NOW)
    book = make_book(tmp_path, cash)
    ex = Executor(mandate, broker, book, Journal(tmp_path / "journal"), Alerter([]),
                  sleeper=lambda s: None, now_fn=lambda: NOW)
    return broker, book, ex


def entry_decision(symbol="QQQ", weight=0.12, stop=92.0):
    checklist = {"sized_in_window": True, "stop_within_bounds": True, "not_chasing": True,
                 "basis": "trend"}
    return Decision(run_type="weekly", action="rebalance", market_regime="neutral",
                    risk_multiplier=1.0, notes_for_human="t",
                    skills_applied=["market-regime", "trend-selection", "position-sizing",
                                    "trade-management", "failure-modes"],
                    positions=[PositionIntent(symbol=symbol, sleeve="trend", target_weight=weight,
                                              thesis="momentum breakout hold", invalidation="close under 50d",
                                              stop_price=stop, confidence=0.6, horizon_days=30,
                                              entry_checklist=checklist)])


def test_entry_fill_applies_to_book_and_places_gtc_stop(mandate, tmp_path):
    broker, book, ex = make_exec(mandate, tmp_path)
    broker.set_quote("QQQ", 99.98, 100.02)
    plan = plan_orders(mandate, book, {"QQQ": make_quote("QQQ", 100)}, {}, entry_decision(), NOW)
    report = ex.execute_plan(plan)
    assert report.filled == 1 and not report.errors
    pos = book.positions["QQQ"]
    assert pos.qty == pytest.approx(1.2) and pos.sleeve == "trend" and pos.stop_price == 92.0
    assert pos.stop_order_tag and report.stops_placed == [pos.stop_order_tag]
    stops = [o for o in broker.open_orders() if o.client_tag == pos.stop_order_tag]
    assert len(stops) == 1 and stops[0].side == "SELL" and stops[0].qty == pytest.approx(1.2)
    assert book.pot_cash < 1000 - 119                      # cash left the pot
    assert book.week_new_positions == 1


def test_stop_out_sync_applies_cooldown(mandate, tmp_path):
    broker, book, ex = make_exec(mandate, tmp_path)
    broker.set_quote("QQQ", 99.98, 100.02)
    plan = plan_orders(mandate, book, {"QQQ": make_quote("QQQ", 100)}, {}, entry_decision(), NOW)
    ex.execute_plan(plan)
    broker.mark("QQQ", 88.0)                               # gap through the 92 stop
    applied = ex.sync_external_fills(NOW)
    assert len(applied) == 1 and applied[0].side == "SELL"
    assert "QQQ" not in book.positions
    assert book.in_cooldown("QQQ", TODAY)
    assert book.realized_pnl["trend"] < 0
    assert book.consecutive_spec_losers == 0               # trend loss doesn't touch spec streak


def test_protective_take_profit_exits_and_cancels_stop(mandate, tmp_path):
    broker, book, ex = make_exec(mandate, tmp_path)
    broker.set_quote("QQQ", 99.98, 100.02)
    plan = plan_orders(mandate, book, {"QQQ": make_quote("QQQ", 100)}, {}, entry_decision(), NOW)
    ex.execute_plan(plan)
    broker.mark("QQQ", 130.0)
    report = ex.execute_protective(
        [ProtectiveAction("take_profit", "QQQ", "trend", sell_qty=book.positions["QQQ"].qty,
                          reason="target hit")],
        {"QQQ": make_quote("QQQ", 130)})
    assert report.realized_pnl > 30
    assert "QQQ" not in book.positions
    assert all(o.order_type != "STP" for o in broker.open_orders()
               for o in [o])                               # no orphan GTC stop survives
    assert broker.open_orders() == []


def test_trail_stop_replaces_gtc_order(mandate, tmp_path):
    broker, book, ex = make_exec(mandate, tmp_path)
    broker.set_quote("QQQ", 99.98, 100.02)
    plan = plan_orders(mandate, book, {"QQQ": make_quote("QQQ", 100)}, {}, entry_decision(), NOW)
    ex.execute_plan(plan)
    old_tag = book.positions["QQQ"].stop_order_tag
    broker.mark("QQQ", 118.0)
    report = ex.execute_protective(
        [ProtectiveAction("trail_stop", "QQQ", "trend", new_stop=110.0, reason="trail")],
        {"QQQ": make_quote("QQQ", 118)})
    pos = book.positions["QQQ"]
    assert pos.stop_price == 110.0
    assert report.stops_replaced and pos.stop_order_tag != old_tag
    live = [o for o in broker.open_orders() if o.client_tag == pos.stop_order_tag]
    assert len(live) == 1
    assert not any(o.client_tag == old_tag for o in broker.open_orders())


def test_rebalance_buys_core(mandate, tmp_path):
    broker, book, ex = make_exec(mandate, tmp_path)
    broker.set_quote("VTI", 299.9, 300.1)
    broker.set_quote("SGOV", 99.99, 100.01)
    report = ex.execute_rebalance(
        [RebalanceIntent("VTI", "BUY", 300.0, "core"), RebalanceIntent("SGOV", "BUY", 200.0, "core")],
        {"VTI": make_quote("VTI", 300), "SGOV": make_quote("SGOV", 100)})
    assert report.filled == 2
    assert book.positions["VTI"].sleeve == "core" and book.positions["SGOV"].sleeve == "core"
    assert book.pot_cash == pytest.approx(500, abs=5)


def test_broker_reject_reported_not_applied(mandate, tmp_path):
    broker, book, ex = make_exec(mandate, tmp_path, cash=1000.0, sim_cash=50.0)  # broker poorer than book
    broker.set_quote("QQQ", 99.98, 100.02)
    plan = plan_orders(mandate, book, {"QQQ": make_quote("QQQ", 100)}, {}, entry_decision(), NOW)
    report = ex.execute_plan(plan)
    assert report.outcomes[0].state == "rejected"
    assert "QQQ" not in book.positions and book.pot_cash == 1000


def test_kill_switch_cancels_engine_orders(mandate, tmp_path):
    broker, book, ex = make_exec(mandate, tmp_path)
    broker.set_quote("QQQ", 99.98, 100.02)
    plan = plan_orders(mandate, book, {"QQQ": make_quote("QQQ", 100)}, {}, entry_decision(), NOW)
    ex.execute_plan(plan)
    assert broker.open_orders()                            # the GTC stop rests
    n = ex.cancel_open_engine_orders()
    assert n == 1 and broker.open_orders() == []
