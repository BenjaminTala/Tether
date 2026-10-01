"""2026-08-25: IB's 17:00 ET reset left a half-dead socket; ib_async requests have no
timeout by default, so one tick sat inside broker calls for 85 minutes on all 7 variants.
The adapter must (a) cap every request and (b) drop the link on a timeout so the
supervisor's reconnect hysteresis takes over."""
from types import SimpleNamespace

import pytest

pytest.importorskip("ib_async")

from ibagent.broker.base import Contract  # noqa: E402
from ibagent.broker.ibkr import BrokerError, IBKRBroker  # noqa: E402
from ibagent.config import BrokerCfg  # noqa: E402


class DeadIB:
    RequestTimeout = 0.0

    def __init__(self):
        self.disconnected = False
        self.hist_kwargs = None

    def reqContractDetails(self, stock):
        return [SimpleNamespace(contract=stock)]

    def reqTickers(self, *contracts):
        raise TimeoutError()

    def reqExecutions(self):
        raise TimeoutError()

    def fills(self):
        return []

    def reqHistoricalData(self, c, **kwargs):
        self.hist_kwargs = kwargs
        return []

    def disconnect(self):
        self.disconnected = True


def _broker(**over):
    cfg = BrokerCfg(**{"port": 4002, "client_id": 1, "connect_timeout_s": 20, **over})
    return IBKRBroker(cfg, ib=DeadIB())


def test_request_timeout_is_set_and_never_undercuts_connect():
    assert _broker(request_timeout_s=30).ib.RequestTimeout == 30.0
    assert _broker(request_timeout_s=10, connect_timeout_s=60).ib.RequestTimeout == 65.0


def test_timed_out_request_fails_fast_and_drops_the_link():
    b = _broker()
    with pytest.raises(BrokerError, match="timed out"):
        b.quote(Contract(symbol="SPY"))
    assert b.ib.disconnected is True
    b.ib.disconnected = False
    with pytest.raises(BrokerError, match="fills_since"):
        from datetime import datetime, timezone
        b.fills_since(datetime.now(timezone.utc))
    assert b.ib.disconnected is True


class LoggedOutIB(DeadIB):
    """TCP accepts but the API greeting never comes: Gateway up, nobody logged in.
    ib_async surfaces this as a bare TimeoutError with no message."""

    def connect(self, *args, **kwargs):
        raise TimeoutError()

    def sleep(self, seconds):
        pass


class NoProcessIB(DeadIB):
    def connect(self, *args, **kwargs):
        raise ConnectionRefusedError(10061, "No connection could be made")

    def sleep(self, seconds):
        pass


def test_connect_failure_names_the_logged_out_state():
    """2026-08-30: Gateway auto-restarted Sunday 12:20 UTC and sat logged out for 10+ hours;
    every variant journaled 'cannot connect ...: ' with an EMPTY reason. The owner must be
    able to tell 'log in on the PC' apart from 'start the Gateway' from the alert alone."""
    cfg = BrokerCfg(port=4002, client_id=1, connect_timeout_s=20)
    b = IBKRBroker(cfg, ib=LoggedOutIB())
    with pytest.raises(BrokerError, match="LOGGED OUT.*manual login"):
        b.connect(attempts=1)
    b = IBKRBroker(cfg, ib=NoProcessIB())
    with pytest.raises(BrokerError, match="connection refused.*needs to be started"):
        b.connect(attempts=1)


def test_daily_bars_uses_short_timeout_and_fails_closed_on_empty():
    b = _broker(bars_timeout_s=7)
    with pytest.raises(BrokerError, match="no historical bars"):
        b.daily_bars(Contract(symbol="SPY"), 30)
    assert b.ib.hist_kwargs["timeout"] == 7.0


class LateReportIB(DeadIB):
    """IB delivers the commission report as its own message after the execution; ib_async
    writes it into the Fill in place when the event loop runs (ib.sleep)."""

    def __init__(self, deliver_report: bool = True):
        super().__init__()
        from datetime import datetime, timezone
        self.fill = SimpleNamespace(
            contract=SimpleNamespace(symbol="XLV"), time=datetime(2026, 10, 1, 18, 6, 3, tzinfo=timezone.utc),
            execution=SimpleNamespace(execId="e1", permId=7, orderId=3, orderRef="s-XLV-STP6", side="SLD",
                                      shares=5.0, price=165.9),
            commissionReport=SimpleNamespace(execId="", commission=0.0))
        self.deliver_report = deliver_report
        self.slept = 0.0

    def reqExecutions(self):
        return [self.fill]

    def sleep(self, seconds):
        self.slept += seconds
        if self.deliver_report:
            self.fill.commissionReport.execId, self.fill.commissionReport.commission = "e1", 1.0


def test_fills_wait_for_the_late_commission_report():
    """2026-10-01: main's XLV stop filled at the broker and was booked with commission 0.0
    (also NVDA 09-14, SPY 09-23) - the fill was converted before IB's separate commission
    report arrived. The fee must be the broker's, not a placeholder zero."""
    from datetime import datetime, timezone
    since = datetime(2026, 10, 1, 18, 5, tzinfo=timezone.utc)
    b = IBKRBroker(BrokerCfg(port=4002, client_id=1, connect_timeout_s=20), ib=LateReportIB())
    [f] = b.fills_since(since)
    assert (f.symbol, f.side, f.commission) == ("XLV", "SELL", 1.0)
    # A report that never comes costs a bounded wait, never a hang or a lost fill.
    b = IBKRBroker(BrokerCfg(port=4002, client_id=1, connect_timeout_s=20),
                   ib=LateReportIB(deliver_report=False), commission_wait_s=1.0)
    [f] = b.fills_since(since)
    assert f.commission == 0.0 and b.ib.slept == 1.0
    assert b.fills_since(datetime(2026, 10, 2, tzinfo=timezone.utc)) == [] and b.ib.slept == 1.0


def test_positions_refuse_to_answer_from_a_dropped_link():
    """2026-09-18: main's VTI quote timed out at 12:23:22 UTC, the adapter dropped the link,
    and the same tick's reconcile read ib_async's emptied position cache as 'SGOV, VTI
    missing' — engine frozen one second later, the daily a frozen HOLD. A dead link is
    missing data (the supervisor journals the error and skips reconcile), never a flat account."""
    b = _broker()
    b.ib.isConnected = lambda: not b.ib.disconnected
    b.ib.positions = lambda account: [SimpleNamespace(
        contract=SimpleNamespace(secType="STK", symbol="VTI"), position=7.0, avgCost=379.98)]
    assert [(p.symbol, p.qty) for p in b.positions()] == [("VTI", 7.0)]
    with pytest.raises(BrokerError, match="timed out"):
        b.quote(Contract(symbol="VTI"))
    b.ib.positions = lambda account: []          # what ib_async serves after a disconnect
    with pytest.raises(BrokerError, match="not connected"):
        b.positions()
