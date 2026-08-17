"""Layered circuit-breaker rules added from the freqtrade Protections review:
weekly/monthly drawdown pauses, HALF_RISK band, account losing-streak cooldown,
and the per-instrument locks (exit cooldown, stop-loss guard, underperformer bench)."""
from datetime import date, timedelta

import pytest

from ibagent.alerts import Alerter
from ibagent.broker.sim import SimBroker, SimConfig
from ibagent.execution import Executor
from ibagent.journal import Journal
from ibagent.risk import plan_orders
from ibagent.sleeves import ProtectiveAction, evaluate_breakers
from tests.conftest import NOW, TODAY, make_book, make_quote
from tests.test_risk import enter, intent, rebalance


# --------------------------------------------------------------------- calendar drawdowns

def test_weekly_drawdown_pauses_entries_until_monday(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    b.ensure_week(TODAY, 1100.0)                           # week opened at 1100, now 1000: -9.1%
    state = evaluate_breakers(mandate, b, b.equity({}, NOW))
    assert state.pause_entries_until == date(2026, 8, 16)  # through Sunday; Monday trades again
    assert "weekly drawdown" in state.pause_entries_reason


def test_monthly_drawdown_pauses_entries_until_month_end(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    b.ensure_month(TODAY, 1150.0)                          # month opened at 1150: -13%
    state = evaluate_breakers(mandate, b, b.equity({}, NOW))
    assert state.pause_entries_until == date(2026, 8, 31)


def test_no_pause_when_anchors_healthy(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    b.ensure_week(TODAY, 1010.0)
    b.ensure_month(TODAY, 1020.0)
    state = evaluate_breakers(mandate, b, b.equity({}, NOW))
    assert state.pause_entries_until is None and state.risk_scale == 1.0


def test_account_losing_streak_cooldown(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    b.consecutive_active_losers = 3
    b.trade_history["QQQ"] = [{"date": TODAY.isoformat(), "realized": -12.0, "r": -1.2}]
    state = evaluate_breakers(mandate, b, b.equity({}, NOW))
    assert state.pause_entries_until == date(2026, 8, 14)  # 2 trading days after the last loss


def test_half_risk_band(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    b.hwm["total"] = 1136.0                                # dd 12%: above 10%, below the 15% halt
    state = evaluate_breakers(mandate, b, b.equity({}, NOW))
    assert state.risk_scale == 0.5 and not state.halt


# --------------------------------------------------------------------- risk layer enforcement

def test_paused_entries_rejected_exits_allowed(mandate, tmp_path):
    b = make_book(tmp_path, 1000)
    enter(b, "SPY", "trend", 1, 200, stop=185)
    b.pause_entries(TODAY + timedelta(days=3), "weekly drawdown")
    quotes = {"SPY": make_quote("SPY", 210), "QQQ": make_quote("QQQ", 100)}
    plan = plan_orders(mandate, b, quotes, {}, rebalance(intent("QQQ", "trend", 0.10, stop=92)), NOW)
    assert [o.intent for o in plan.orders] == ["exit"]      # SPY exit still happens
    assert any("entries paused" in r.reason for r in plan.rejections)


def test_half_risk_halves_new_position_size(mandate, tmp_path):
    b = make_book(tmp_path, 2000)
    b.hwm["total"] = 2280.0                                # dd 12.3% -> half risk
    plan = plan_orders(mandate, b, {"QQQ": make_quote("QQQ", 100)}, {},
                       rebalance(intent("QQQ", "trend", 0.12, stop=92)), NOW)
    [o] = plan.orders
    assert o.req.qty == pytest.approx(1.25)                # full risk would size 2.4


# --------------------------------------------------------------------- per-instrument locks

def make_exec(mandate, tmp_path, cash=1000.0):
    broker = SimBroker(SimConfig(initial_cash=cash))
    broker.connect()
    broker.set_time(NOW)
    book = make_book(tmp_path, cash)
    ex = Executor(mandate, broker, book, Journal(tmp_path / "journal"), Alerter([]),
                  sleeper=lambda s: None, now_fn=lambda: NOW)
    return broker, book, ex


def test_any_full_exit_starts_reentry_cooldown(mandate, tmp_path):
    broker, book, ex = make_exec(mandate, tmp_path)
    broker.set_quote("QQQ", 99.98, 100.02)
    plan = plan_orders(mandate, book, {"QQQ": make_quote("QQQ", 100)}, {},
                       rebalance(intent("QQQ", "trend", 0.12, stop=92)), NOW)
    ex.execute_plan(plan)
    broker.mark("QQQ", 130.0)
    ex.execute_protective([ProtectiveAction("take_profit", "QQQ", "trend",
                                            sell_qty=book.positions["QQQ"].qty, reason="target")],
                          {"QQQ": make_quote("QQQ", 130)})
    assert book.in_cooldown("QQQ", TODAY + timedelta(days=4))   # 5 sessions, a WINNING exit too


def test_underperformer_gets_benched(mandate, tmp_path):
    broker, book, ex = make_exec(mandate, tmp_path)
    book.trade_history["NVDA"] = [
        {"date": (TODAY - timedelta(days=30 - i * 7)).isoformat(), "realized": -8.0, "r": -0.4}
        for i in range(3)]
    broker.set_quote("NVDA", 99.98, 100.02)
    plan = plan_orders(mandate, book, {"NVDA": make_quote("NVDA", 100)}, {},
                       rebalance(intent("NVDA", "trend", 0.12, stop=92)), NOW)
    ex.execute_plan(plan)
    broker.mark("NVDA", 94.0)                              # close the 4th trade at a loss
    ex.execute_protective([ProtectiveAction("take_profit", "NVDA", "trend",
                                            sell_qty=book.positions["NVDA"].qty, reason="exit")],
                          {"NVDA": make_quote("NVDA", 94)})
    assert book.recent_r_sum("NVDA", 4) is not None
    assert book.recent_r_sum("NVDA", 4) <= -1.0
    # benched for ~60 sessions, i.e. locked far beyond the plain 5-session exit cooldown
    assert book.in_cooldown("NVDA", TODAY + timedelta(days=60))


def test_stop_loss_guard_locks_after_repeat_stopouts(mandate, tmp_path):
    broker, book, ex = make_exec(mandate, tmp_path)
    book.stopout_history["QQQ"] = [(TODAY - timedelta(days=20)).isoformat()]   # one prior stop-out
    broker.set_quote("QQQ", 99.98, 100.02)
    plan = plan_orders(mandate, book, {"QQQ": make_quote("QQQ", 100)}, {},
                       rebalance(intent("QQQ", "trend", 0.12, stop=92)), NOW)
    ex.execute_plan(plan)
    broker.mark("QQQ", 88.0)                               # second stop-out inside the window
    ex.sync_external_fills(NOW)
    assert book.stopouts_within("QQQ", TODAY, 60) == 2
    assert book.in_cooldown("QQQ", TODAY + timedelta(days=35))  # 30 sessions >> the 5-session default


# --------------------------------------------------------------------- whole-share mode

def test_whole_share_mode_floors_or_rejects(md, tmp_path):
    from ibagent.config import mandate_from_dict
    md["broker"]["fractional_shares"] = False
    md["capital"]["min_position_usd"] = 90
    m = mandate_from_dict(md)
    b = make_book(tmp_path, 1000)
    quotes = {"XLF": make_quote("XLF", 50), "NVDA": make_quote("NVDA", 800)}
    d = rebalance(intent("XLF", "trend", 0.12, stop=46), intent("NVDA", "trend", 0.12, stop=736))
    plan = plan_orders(m, b, quotes, {}, d, NOW)
    # XLF: risk $10 / $4 stop distance = 2.5 -> floored to 2 whole shares ($100 >= $90 floor)
    xlf = [o for o in plan.orders if o.req.symbol == "XLF"]
    assert len(xlf) == 1 and xlf[0].req.qty == 2.0
    # NVDA: one share $800 exceeds the $120 position budget -> rejected, not rounded up
    assert any(r.symbol == "NVDA" and "fractional" in r.reason for r in plan.rejections)


# --------------------------------------------------------------------- persistence

def test_new_state_survives_roundtrip(mandate, tmp_path):
    from ibagent.book import Book
    b = make_book(tmp_path, 1000)
    b.ensure_week(TODAY, 1050.0)
    b.ensure_month(TODAY, 1080.0)
    b.pause_entries(TODAY + timedelta(days=5), "weekly drawdown")
    b.consecutive_active_losers = 2
    b.stopout_history["QQQ"] = [TODAY.isoformat()]
    b.trade_history["QQQ"] = [{"date": TODAY.isoformat(), "realized": -5.0, "r": -0.5}]
    b.save()
    b2 = Book.load(b.path)
    assert b2.week_start_equity == 1050.0 and b2.month_start_equity == 1080.0
    assert b2.entries_paused(TODAY + timedelta(days=5))
    assert b2.consecutive_active_losers == 2
    assert b2.stopout_history == b.stopout_history and b2.trade_history == b.trade_history
