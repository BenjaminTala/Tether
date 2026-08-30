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
