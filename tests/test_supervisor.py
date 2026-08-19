from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ibagent.alerts import Alerter
from ibagent.broker.base import Fill, OrderRequest
from ibagent.broker.sim import SimBroker, SimConfig
from ibagent.config import mandate_from_dict
from ibagent.llm.runner import FakeRunner, RunResult
from ibagent.supervisor import Supervisor
from ibagent.watchdog import check as watchdog_check
from tests.conftest import NOW


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def env(md, tmp_path):
    md["llm"]["sandbox"]["runs_root"] = str(tmp_path / "runs")
    md["journal"]["dir"] = str(tmp_path / "journal")
    md["kill_switch"]["file"] = str(tmp_path / "KILL")
    m = mandate_from_dict(md)
    broker = SimBroker(SimConfig(initial_cash=1000.0))
    broker.connect()
    broker.set_time(NOW)
    clock = Clock(NOW)
    sup = Supervisor(m, broker, runner=FakeRunner([]), data_dir=tmp_path, alerter=Alerter([]),
                     now_fn=clock, sleeper=lambda s: None, feeds=[],
                     skills_dir=tmp_path / "no-skills")
    return m, broker, sup, clock, tmp_path


def enter(sup, broker, symbol, sleeve, qty, price, with_broker=True):
    sup.book.apply_contribution(0.0001)                    # ensure book initialized paths exist
    f = Fill("1", "t", symbol, "BUY", qty, price, 0.35, NOW)
    sup.book.apply_fill(f, sleeve, entry_meta={"stop_price": price * 0.9,
                                               "stop_order_tag": f"stp-{symbol}"})
    if with_broker:
        broker.force_position(symbol, qty, price)
    broker.set_quote(symbol, price - 0.02, price + 0.02)


def test_tick_writes_heartbeat_and_survives_empty_book(env):
    m, broker, sup, clock, tmp = env
    sup.tick(clock())
    hb = (tmp / "heartbeat.txt").read_text(encoding="utf-8")
    assert hb.startswith("2026-08-12")
    assert not sup.book.frozen and not sup.book.halted


def test_reconcile_mismatch_freezes(env):
    m, broker, sup, clock, tmp = env
    enter(sup, broker, "SPY", "trend", 2.0, 100.0, with_broker=False)   # book says 2, broker has 0
    sup.tick(clock())
    assert sup.book.frozen and "SPY" in sup.book.frozen_reason


def test_shared_account_extra_broker_positions_ignored(env):
    m, broker, sup, clock, tmp = env
    broker.force_position("AAPL", 10, 150.0)               # the human's own shares
    sup.tick(clock())
    assert not sup.book.frozen


def test_kill_switch_cancels_and_blocks(env):
    m, broker, sup, clock, tmp = env
    broker.set_quote("QQQ", 99.98, 100.02)
    broker.place(OrderRequest(client_tag="s2026-QQQ-STP", symbol="QQQ", side="SELL", qty=0,
                              order_type="STP", stop_price=90.0, tif="GTC"))  # qty 0 -> rejected; place real
    broker.force_position("QQQ", 1, 100)
    st = broker.place(OrderRequest(client_tag="s2026-QQQ-STP", symbol="QQQ", side="SELL", qty=1,
                                   order_type="STP", stop_price=90.0, tif="GTC"))
    assert st.state == "submitted"
    Path(m.kill_switch.file).write_text("KILL", encoding="utf-8")
    sup.tick(clock())
    assert broker.open_orders() == []
    assert sup.state.kill_handled
    Path(m.kill_switch.file).unlink()
    sup.tick(clock())
    assert not sup.state.kill_handled                      # auto-reset once cleared


def test_total_drawdown_halt_liquidates_active(env):
    m, broker, sup, clock, tmp = env
    enter(sup, broker, "QQQ", "trend", 2.0, 100.0)
    sup.book.hwm["total"] = 1500.0                         # equity ~1000 -> dd > 15%
    sup.tick(clock())
    assert sup.book.halted
    assert "QQQ" not in sup.book.positions                 # liquidated to cash


def test_daily_report_and_schedule_marks(env):
    m, broker, sup, clock, tmp = env
    clock.now = datetime(2026, 8, 12, 20, 30, tzinfo=timezone.utc)      # 16:30 ET, after close
    sup.tick(clock.now)
    assert sup.state.last_report == "2026-08-12"
    assert sup.state.last_daily == "2026-08-12"            # daily agent job also fired (HOLD fallback)
    kinds = [e["kind"] for e in sup.journal.tail(50)]
    assert "daily_report" in kinds
    # second tick the same day does not repeat the jobs
    n = len(sup.journal.tail(200))
    sup.tick(clock.now + timedelta(minutes=5))
    kinds2 = [e["kind"] for e in sup.journal.tail(200)]
    assert kinds2.count("daily_report") == 1


def test_weekend_runs_nothing(env):
    m, broker, sup, clock, tmp = env
    clock.now = datetime(2026, 8, 15, 15, 0, tzinfo=timezone.utc)       # Saturday
    sup.tick(clock.now)
    assert sup.state.last_daily == "" and sup.state.last_report == ""


def test_capital_ledger_syncs_into_book(env):
    m, broker, sup, clock, tmp = env
    from ibagent.capital import CapitalLedger
    ledger = CapitalLedger(tmp / "capital_events.jsonl")
    ledger.init_seed(1000.0)
    sup.sync_capital()
    assert sup.book.pot_cash == pytest.approx(1000.0)
    sup.sync_capital()                                     # idempotent
    assert sup.book.pot_cash == pytest.approx(1000.0)
    ledger.add(500.0)
    sup.tick(clock())                                      # picked up mid-run, no restart
    assert sup.book.pot_cash == pytest.approx(1500.0)
    ledger.withdraw(300.0)
    sup.sync_capital()
    assert sup.book.pending_withdrawal_usd == pytest.approx(300.0)
    assert sup.book.deployable_cash(clock().date()) == pytest.approx(1200.0)
    sup.sync_capital()                                     # withdrawal not double-requested
    assert sup.book.pending_withdrawal_usd == pytest.approx(300.0)


def test_watchdog(env, tmp_path):
    m, broker, sup, clock, tmp = env
    hb = tmp / "heartbeat.txt"
    st = tmp / "watchdog_state.json"
    sup.tick(clock())                                      # writes heartbeat at NOW

    class CountingAlerter(Alerter):
        def __init__(self):
            super().__init__([])
            self.sent = []

        def send(self, level, title, body="", dedupe=True):
            self.sent.append((level, title))
            return True

    a = CountingAlerter()
    args = dict(heartbeat_path=hb, book_path=tmp / "book.json", alerter=a, state_path=st)
    assert watchdog_check(m, now=NOW + timedelta(minutes=5), **args) == 0
    assert a.sent == []                                    # healthy, never-stale: silent
    # outage begins: exactly ONE critical, then silence on the 5-min rechecks
    assert watchdog_check(m, now=NOW + timedelta(minutes=30), **args) == 1
    assert watchdog_check(m, now=NOW + timedelta(minutes=35), **args) == 1
    assert watchdog_check(m, now=NOW + timedelta(minutes=40), **args) == 1
    assert [lvl for lvl, _ in a.sent] == ["critical"]
    # an hour in: one warning reminder
    assert watchdog_check(m, now=NOW + timedelta(minutes=95), **args) == 1
    assert [lvl for lvl, _ in a.sent] == ["critical", "warning"]
    # recovery: one info, state cleared
    hb.write_text((NOW + timedelta(minutes=100)).isoformat(), encoding="utf-8")
    assert watchdog_check(m, now=NOW + timedelta(minutes=101), **args) == 0
    assert [lvl for lvl, _ in a.sent] == ["critical", "warning", "info"]
    # missing heartbeat while a book exists = same episode logic
    missing = tmp / "nope.txt"
    (tmp / "book.json").write_text("{}", encoding="utf-8")
    args2 = dict(heartbeat_path=missing, book_path=tmp / "book.json", alerter=a, state_path=st)
    assert watchdog_check(m, now=NOW, **args2) == 1
    assert watchdog_check(m, now=NOW + timedelta(minutes=5), **args2) == 1
    assert [lvl for lvl, _ in a.sent] == ["critical", "warning", "info", "critical"]
