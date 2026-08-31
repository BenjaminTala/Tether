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


def test_stop_fill_racing_reconcile_does_not_freeze(env):
    """2026-08-28 bold: NVDA's GTC stop filled between the tick's fill sync and positions();
    reconcile saw 'NVDA book=3 broker=0 (missing)' and froze the engine for its own exit."""
    m, broker, sup, clock, tmp = env
    enter(sup, broker, "SPY", "trend", 2.0, 100.0)
    real_positions = broker.positions

    def positions_after_stop_fired():
        # the stop fires "now": broker is flat and the fill exists, but only after this call
        broker._positions.pop("SPY", None)
        broker._fills.append(Fill("9", "stp-SPY", "SPY", "SELL", 2.0, 90.0, 0.35,
                                  NOW + timedelta(seconds=5)))
        broker.positions = real_positions
        return real_positions()
    broker.positions = positions_after_stop_fired
    sup.tick(clock())
    assert not sup.book.frozen
    assert "SPY" not in sup.book.positions            # the stop fill was applied instead
    assert _journal_kinds(tmp, "fill")


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
    clock.now = datetime(2026, 8, 12, 19, 0, tzinfo=timezone.utc)       # 15:00 ET, inside RTH
    sup.tick(clock.now)
    assert sup.state.last_daily == "2026-08-12"            # daily agent job fired (HOLD fallback)
    assert sup.state.last_report == ""                     # report waits for 16:20
    clock.now = datetime(2026, 8, 12, 20, 30, tzinfo=timezone.utc)      # 16:30 ET, after close
    sup.tick(clock.now)
    assert sup.state.last_report == "2026-08-12"
    kinds = [e["kind"] for e in sup.journal.tail(80)]
    assert "daily_report" in kinds
    # second tick the same day does not repeat the jobs
    sup.tick(clock.now + timedelta(minutes=5))
    kinds2 = [e["kind"] for e in sup.journal.tail(200)]
    assert kinds2.count("daily_report") == 1


def test_missed_decision_runs_do_not_fire_after_hours(env):
    """2026-08-24: Gateway was down all session; login came after the close. The overdue
    weekly must NOT burn itself into a closed market — it rolls to the next RTH morning."""
    m, broker, sup, clock, tmp = env
    clock.now = datetime(2026, 8, 12, 22, 30, tzinfo=timezone.utc)      # 18:30 ET Monday-ish
    sup.tick(clock.now)
    assert sup.state.last_weekly == "" and sup.state.last_daily == ""   # nothing consumed
    clock.now = datetime(2026, 8, 13, 14, 30, tzinfo=timezone.utc)      # next day 10:30 ET, RTH
    sup.tick(clock.now)
    assert sup.state.last_weekly == "2026-08-10"                        # made up next morning
    assert sup.state.last_daily == "2026-08-13"


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


class _CountingAlerter(Alerter):
    def __init__(self):
        super().__init__([])
        self.sent = []

    def send(self, level, title, body="", dedupe=True):
        self.sent.append((level, title))
        return True


def _journal_kinds(tmp, kind, where=None):
    out = []
    for f in sorted((tmp / "journal").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            j = __import__("json").loads(line)
            if j["kind"] == kind and (where is None or j["payload"].get("where") == where):
                out.append(j)
    return out


def test_connection_outage_hysteresis(env):
    """A weekend-long Gateway outage journals ONE error and alerts once at the start,
    at most hourly after, and summarizes on recovery (2026-08-22/23: 211 identical
    errors + a Telegram ping every 30 min per variant)."""
    m, broker, sup, clock, tmp = env
    a = _CountingAlerter()
    sup.alerter = a
    broker.is_connected = lambda: False
    def refuse():
        raise ConnectionError("refused")
    broker.connect = refuse

    sup._ensure_connected()                                # outage starts: one error, one alert
    for i in range(1, 8):                                  # 35 min of 5-min retries: silence
        clock.now = NOW + timedelta(minutes=5 * i)
        assert sup._ensure_connected() is False
    assert len(_journal_kinds(tmp, "error", "connect")) == 1
    assert [lvl for lvl, _ in a.sent] == ["warning"]

    clock.now = NOW + timedelta(minutes=65)                # an hour in: one reminder
    sup._ensure_connected()
    assert [lvl for lvl, _ in a.sent] == ["warning", "warning"]
    assert a.sent[1][1] == "broker still unreachable"
    assert len(_journal_kinds(tmp, "error", "connect")) == 1

    def reconnect():                                       # recovery: one summary each way
        broker.is_connected = lambda: True
    broker.connect = reconnect
    clock.now = NOW + timedelta(minutes=70)
    assert sup._ensure_connected() is True
    recons = [j for j in _journal_kinds(tmp, "broker") if j["payload"].get("event") == "reconnected"]
    assert recons[-1]["payload"]["down_minutes"] == 70
    assert recons[-1]["payload"]["failed_attempts"] == 9
    assert [lvl for lvl, _ in a.sent] == ["warning", "warning", "info"]

    assert sup._ensure_connected() is True                 # healthy again: silence
    assert len(a.sent) == 3
    assert sup._conn_down_since is None and sup._conn_fail_count == 0


def test_bars_warning_once_per_symbol_per_day(env):
    """Repeated historical-data failures warn once per symbol per day, and recovery is
    journaled to bracket the window (2026-08-21: ~800 identical bars warnings/variant)."""
    m, broker, sup, clock, tmp = env

    def no_bars(contract, days):
        raise RuntimeError(f"no historical bars for {contract.symbol}")
    broker.daily_bars = no_bars
    for _ in range(5):
        sup._bars(["SPY", "QQQ"], clock())
    warns = _journal_kinds(tmp, "warning", "bars")
    assert sorted(w["payload"]["symbol"] for w in warns) == ["QQQ", "SPY"]

    from ibagent.broker.base import Bar
    broker.daily_bars = lambda contract, days: [Bar(NOW, 100.0, 101.0, 99.0, 100.5, 1e6)]
    sup._bars(["SPY"], clock())
    rec = [j for j in _journal_kinds(tmp, "broker") if j["payload"].get("event") == "bars_recovered"]
    assert [j["payload"]["symbol"] for j in rec] == ["SPY"]
    sup._bars(["SPY"], clock())                            # no duplicate recovery record
    assert len([j for j in _journal_kinds(tmp, "broker")
                if j["payload"].get("event") == "bars_recovered"]) == 1

    clock.now = NOW + timedelta(days=1)                    # new day: the warning may repeat
    broker.daily_bars = no_bars
    sup._bars(["QQQ"], clock())
    assert len([w for w in _journal_kinds(tmp, "warning", "bars")
                if w["payload"]["symbol"] == "QQQ"]) == 2


def test_qa_during_outage_still_shows_the_book(env):
    """2026-08-24: with the Gateway down, the owner's question got portfolio.json = {} and
    the assistant replied 'no positions loaded' while VTI+SGOV sat in the book. A book that
    cannot be marked is still the truth — the Q&A bundle must say DEGRADED, not empty."""
    m, broker, sup, clock, tmp = env
    enter(sup, broker, "VTI", "core", 3.0, 380.0)
    sup._quotes = lambda symbols: {}                       # broker down: no prices at all
    sup.qa_runner = FakeRunner([RunResult(ok=False, decision=None, text="answer")])
    sup._qa_job("what do I hold?", clock())
    req = sup.qa_runner.requests[0]
    pf = __import__("json").loads((req.bundle_dir / "portfolio.json").read_text(encoding="utf-8"))
    assert pf["status"].startswith("DEGRADED")
    assert [p["symbol"] for p in pf["positions"]] == ["VTI"]
    assert pf["positions"][0]["qty"] == 3.0
    assert "'status'" in req.prompt
    assert _journal_kinds(tmp, "qa")[-1]["payload"]["ok"] is True


def test_bars_circuit_breaker_skips_rest_of_pass(env):
    """2026-08-25: at the open, 48 consecutive history requests each hit ib_async's 60s
    timeout on all 7 variants — every tick was blocked for 48 minutes and the 09:45 ET
    weekly ran at 10:22. After BARS_FAIL_STREAK consecutive failures in one pass the
    remaining symbols are skipped (one warning per day), and a later pass retries them."""
    from ibagent.broker.base import Bar
    from ibagent.supervisor import BARS_FAIL_STREAK
    m, broker, sup, clock, tmp = env
    calls = []

    def no_bars(contract, days):
        calls.append(contract.symbol)
        raise RuntimeError(f"no historical bars for {contract.symbol}")
    broker.daily_bars = no_bars
    syms = [f"S{i}" for i in range(20)]
    sup._bars(syms, clock())
    assert len(calls) == BARS_FAIL_STREAK
    skipped = [w for w in _journal_kinds(tmp, "warning", "bars") if "skipped" in w["payload"]]
    assert len(skipped) == 1 and skipped[0]["payload"]["skipped"] == 20 - BARS_FAIL_STREAK
    sup._bars(syms, clock())                               # still down: no second circuit warning
    assert len([w for w in _journal_kinds(tmp, "warning", "bars") if "skipped" in w["payload"]]) == 1

    calls.clear()
    broker.daily_bars = lambda contract, days: [Bar(NOW, 100.0, 101.0, 99.0, 100.5, 1e6)]
    out = sup._bars(syms, clock())                         # farm back: every symbol fetched
    assert sorted(out) == sorted(syms)

    calls.clear()
    broker.daily_bars = no_bars
    clock.now = NOW + timedelta(days=1)                    # new day, fresh cache: two good, then dead
    good = {"S0", "S1"}
    broker.daily_bars = lambda c, d: [Bar(NOW, 1.0, 1.0, 1.0, 1.0, 1.0)] if c.symbol in good else no_bars(c, d)
    out = sup._bars(syms, clock())
    assert set(out) == good and len(calls) == BARS_FAIL_STREAK


def test_bars_circuit_breaker_still_serves_cached_symbols(env):
    """2026-08-26: scalper's held QQQ/SPY/XLF were fetched for the protective pass and sat
    in the day cache, yet all 13 bundles showed only AAPL/AMD/AVGO — the breaker `break`-ed
    out of the loop before reaching cached symbols that sort after the failing ones. Cached
    history must be served regardless of where the farm died in the pass."""
    from ibagent.broker.base import Bar
    from ibagent.supervisor import BARS_FAIL_STREAK
    m, broker, sup, clock, tmp = env
    ok = lambda contract, days: [Bar(NOW, 100.0, 101.0, 99.0, 100.5, 1e6)]
    broker.daily_bars = ok
    sup._bars(["QQQ", "SPY", "XLF"], clock())             # protective pass: held symbols cached
    calls = []

    def dead(contract, days):
        calls.append(contract.symbol)
        raise RuntimeError(f"no historical bars for {contract.symbol}")
    broker.daily_bars = dead
    scan = ["AAPL", "ABBV", "ADBE", "AMZN", "META", "QQQ", "SPY", "XLF"]
    out = sup._bars(scan, clock())                          # farm dead for the scan surface
    assert len(calls) == BARS_FAIL_STREAK
    assert sorted(out) == ["QQQ", "SPY", "XLF"]             # held book still visible
    skipped = [w for w in _journal_kinds(tmp, "warning", "bars") if "skipped" in w["payload"]]
    assert skipped[0]["payload"]["skipped"] == 2            # only the UNCACHED remainder counts


def test_refresh_bars_is_bounded_and_skips_known_failures(env):
    """2026-08-26: the intraday focus refetch retried every failing symbol at 20s each,
    silently — ~9 min between bundle stamp and model start, 13 times. It must stop after
    BARS_FAIL_STREAK failures and not retry symbols that already failed today."""
    from datetime import date
    from ibagent.broker.base import Bar
    from ibagent.supervisor import BARS_FAIL_STREAK
    m, broker, sup, clock, tmp = env
    calls = []

    def dead(contract, days):
        calls.append(contract.symbol)
        raise RuntimeError("no historical bars")
    broker.daily_bars = dead
    sup._bars(["ABBV"], clock())                            # ABBV failed + warned today
    calls.clear()
    fresh = sup._refresh_bars(["ABBV", "S1", "S2", "S3", "S4", "S5"], date(2026, 8, 12))
    assert fresh == {} and "ABBV" not in calls and len(calls) == BARS_FAIL_STREAK

    calls.clear()

    def alive(contract, days):
        calls.append(contract.symbol)
        return [Bar(NOW, 100.0, 101.0, 99.0, 100.5, 1e6)]
    broker.daily_bars = alive
    fresh = sup._refresh_bars(["SPY", "QQQ"], date(2026, 8, 12))
    assert sorted(fresh) == ["QQQ", "SPY"] and sorted(calls) == ["QQQ", "SPY"]
    assert sup._bars_cache["SPY"]                            # refreshed bars land in the cache


def test_fleet_digest_fires_friday_and_covers_the_whole_week(env, monkeypatch):
    """FLEET.md 'Week of 2026-08-24' said 'decisions 0' for all 7 variants: the digest fired
    MONDAY after the close, so each 'week' held one day (and tail(60) capped the count)."""
    from ibagent.journal import Journal
    m, broker, sup, clock, tmp = env
    monkeypatch.chdir(tmp)
    j = Journal(tmp / "data" / "journal")
    monday = datetime(2026, 8, 24, 14, 0, tzinfo=timezone.utc)
    for i in range(70):                                     # more than the old tail(60) cap
        j.record("decision", {"action": "no_change", "lessons": f"l{i}"}, ts=monday + timedelta(hours=i))
    j.record("decision", {"action": "no_change"}, ts=monday - timedelta(days=3))   # last week
    sup._maybe_fleet_digest(monday)                          # Monday: nothing yet
    assert not (tmp / "FLEET.md").exists()
    sup._maybe_fleet_digest(monday + timedelta(days=4, hours=7))   # Friday after the close
    text = (tmp / "FLEET.md").read_text(encoding="utf-8")
    assert "## Week of 2026-08-24" in text and "decisions 70" in text and "lesson: l69" in text
    sup._maybe_fleet_digest(monday + timedelta(days=4, hours=8))   # once per week
    assert text.count("Week of") == 1 == (tmp / "FLEET.md").read_text(encoding="utf-8").count("Week of")


def test_model_runs_wait_for_the_order_window(md, tmp_path):
    """2026-08-31: scalper's first intraday scan fired at ~09:31 ET, inside the open
    no-trade buffer; the plan was a guaranteed 'outside RTH trade window' hold — one model
    run wasted. Sniper's 09:34 ET event run on 2026-08-28 was the same failure via the news
    gate. Runs that produce orders fire only while orders can fill (RTH minus the buffers)."""
    md["llm"]["sandbox"]["runs_root"] = str(tmp_path / "runs")
    md["journal"]["dir"] = str(tmp_path / "journal")
    md["kill_switch"]["file"] = str(tmp_path / "KILL")
    md["cadence"]["intraday_minutes"] = 30
    m = mandate_from_dict(md)
    broker = SimBroker(SimConfig(initial_cash=1000.0))
    broker.connect()
    broker.set_time(NOW)
    clock = Clock(NOW)
    sup = Supervisor(m, broker, runner=FakeRunner([]), data_dir=tmp_path, alerter=Alerter([]),
                     now_fn=clock, sleeper=lambda s: None, feeds=[],
                     skills_dir=tmp_path / "no-skills")

    buffers = (m.execution.no_trade_first_minutes, m.execution.no_trade_last_minutes)
    assert buffers == (15, 10)                               # mandate values this test assumes

    clock.now = datetime(2026, 8, 12, 13, 35, tzinfo=timezone.utc)   # 09:35 ET: RTH, in buffer
    assert not sup._orders_can_fill(clock.now)
    sup.tick(clock.now)
    assert sup.state.last_intraday_ts == 0.0                 # scan NOT consumed in the buffer

    clock.now = datetime(2026, 8, 12, 13, 46, tzinfo=timezone.utc)   # 09:46 ET: window open
    assert sup._orders_can_fill(clock.now)
    sup.tick(clock.now)
    assert sup.state.last_intraday_ts == clock.now.timestamp()       # first scan fires now

    sup.state.last_intraday_ts = 0.0                         # close buffer: 15:52 ET
    clock.now = datetime(2026, 8, 12, 19, 52, tzinfo=timezone.utc)
    assert not sup._orders_can_fill(clock.now)
    sup.tick(clock.now)
    assert sup.state.last_intraday_ts == 0.0
