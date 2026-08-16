import math
from datetime import date, datetime, timezone

import pytest

ib_async = pytest.importorskip("ib_async")
from ib_async import Trade, Order, Stock  # noqa: E402
from ib_async.objects import AccountValue, BarData, TradeLogEntry  # noqa: E402
from ib_async.order import OrderStatus as IBOrderStatus  # noqa: E402

from ibagent.broker.base import Contract, OrderRequest  # noqa: E402
from ibagent.broker.ibkr import (BrokerError, bar_from_ib, build_order, duration_str, map_status,  # noqa: E402
                                 order_id_of, parse_account_values, to_ib_stock, trade_to_status)


def _req(**kw) -> OrderRequest:
    base = dict(client_tag="w2026-08-17-AAPL-BUY", symbol="AAPL", side="BUY", qty=1.2345, order_type="LMT",
                limit_price=190.123, tif="DAY")
    base.update(kw)
    return OrderRequest(**base)


def test_build_limit_order_fields():
    o = build_order(_req())
    assert o.orderType == "LMT" and o.action == "BUY"
    assert o.totalQuantity == 1.2345 and o.lmtPrice == 190.12
    assert o.tif == "DAY" and o.orderRef == "w2026-08-17-AAPL-BUY" and o.transmit is True and o.outsideRth is False


def test_build_stop_orders():
    s = build_order(_req(order_type="STP", side="SELL", stop_price=180.456, limit_price=None, tif="GTC"))
    assert s.orderType == "STP" and s.auxPrice == 180.46 and s.tif == "GTC"
    sl = build_order(_req(order_type="STP LMT", side="SELL", stop_price=180.0, limit_price=178.0, tif="GTC"))
    assert sl.orderType == "STP LMT" and sl.auxPrice == 180.0 and sl.lmtPrice == 178.0
    m = build_order(_req(order_type="MKT", limit_price=None))
    assert m.orderType == "MKT"


def test_build_order_validation():
    with pytest.raises(BrokerError, match="limit price"):
        build_order(_req(limit_price=None))
    with pytest.raises(BrokerError, match="stop price"):
        build_order(_req(order_type="STP", stop_price=None))
    with pytest.raises(BrokerError, match="rounds to zero"):
        build_order(_req(qty=0.00001))


def test_to_ib_stock_defaults_and_overrides():
    s = to_ib_stock(Contract("CSPX", exchange="LSEETF", currency="USD"))
    assert (s.symbol, s.exchange, s.currency) == ("CSPX", "LSEETF", "USD")
    s2 = to_ib_stock(Contract("AAPL"))
    assert (s2.exchange, s2.currency) == ("SMART", "USD")


@pytest.mark.parametrize("status,filled,remaining,expected", [
    ("Submitted", 0, 2, "submitted"), ("PreSubmitted", 0, 2, "submitted"), ("Submitted", 1, 1, "partially_filled"),
    ("Filled", 2, 0, "filled"), ("Cancelled", 0, 2, "cancelled"), ("ApiCancelled", 0, 2, "cancelled"),
    ("Inactive", 0, 2, "rejected"), ("PendingSubmit", 0, 2, "pending"), ("Weird", 0, 2, "unknown"),
])
def test_map_status(status, filled, remaining, expected):
    assert map_status(status, filled, remaining) == expected


def test_trade_to_status_and_ids():
    order = Order(orderId=7, permId=0, action="SELL", totalQuantity=2, orderType="STP", auxPrice=95, orderRef="stop-1")
    st = IBOrderStatus(orderId=7, status="PreSubmitted", filled=0, remaining=2, avgFillPrice=0.0)
    trade = Trade(contract=Stock("AAPL", "SMART", "USD"), order=order, orderStatus=st, fills=[],
                  log=[TradeLogEntry(time=datetime(2026, 8, 17, 14, tzinfo=timezone.utc), status="PreSubmitted", message="")])
    s = trade_to_status(trade)
    assert s.broker_order_id == "o7" and s.client_tag == "stop-1" and s.state == "submitted" and s.avg_fill_price is None
    order.permId = 123456
    assert order_id_of(order) == "123456"
    trade.log.append(TradeLogEntry(time=datetime.now(timezone.utc), status="Inactive", message="Error 201: Order rejected - reason: insufficient funds"))
    trade.orderStatus.status = "Inactive"
    s2 = trade_to_status(trade)
    assert s2.state == "rejected" and "insufficient funds" in s2.reason


def test_parse_account_values_prefers_base_currency():
    vals = [AccountValue("DU1", "NetLiquidation", "1050.55", "USD", ""),
            AccountValue("DU1", "TotalCashValue", "500.10", "USD", ""),
            AccountValue("DU1", "TotalCashValue", "0.00", "EUR", ""),
            AccountValue("DU1", "SettledCash", "400.00", "USD", ""),
            AccountValue("DU1", "Cushion", "0.9", "", "")]
    a = parse_account_values(vals, "USD", datetime.now(timezone.utc))
    assert (a.net_liquidation, a.total_cash, a.settled_cash) == (1050.55, 500.10, 400.00)
    with pytest.raises(BrokerError, match="incomplete"):
        parse_account_values(vals[:1], "USD", datetime.now(timezone.utc))
    # missing SettledCash falls back to TotalCashValue (logged)
    a2 = parse_account_values(vals[:2], "USD", datetime.now(timezone.utc))
    assert a2.settled_cash == 500.10


def test_bar_from_ib_and_duration():
    b = bar_from_ib(BarData(date=date(2026, 8, 14), open=1, high=2, low=0.5, close=1.5, volume=1000, average=1.2, barCount=10))
    assert b.ts == datetime(2026, 8, 14, tzinfo=timezone.utc) and b.close == 1.5
    b2 = bar_from_ib(BarData(date="20260814", open=1, high=2, low=0.5, close=1.5, volume=1000, average=1.2, barCount=10))
    assert b2.ts.date() == date(2026, 8, 14)
    assert duration_str(30) == "30 D" and duration_str(365) == "365 D" and duration_str(400) == "2 Y"
    with pytest.raises(ValueError):
        duration_str(0)
