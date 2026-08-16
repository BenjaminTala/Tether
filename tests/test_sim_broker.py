from datetime import datetime, timedelta, timezone

import pytest

from ibagent.broker.base import Bar, Contract, OrderRequest
from ibagent.broker.sim import SimBroker, SimConfig, SimError

T0 = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)   # Monday
AAPL = Contract("AAPL")


def mk(cash=1000.0, **kw) -> SimBroker:
    b = SimBroker(SimConfig(initial_cash=cash, slippage_bps=0.0, **kw), now=T0)
    b.connect()
    b.set_quote("AAPL", bid=99.9, ask=100.1, last=100.0)
    return b


def buy(b, qty, limit, tag="t1", tif="DAY", otype="LMT", stop=None):
    return b.place(OrderRequest(client_tag=tag, symbol="AAPL", side="BUY", qty=qty, order_type=otype,
                                limit_price=limit, stop_price=stop, tif=tif))


def sell(b, qty, limit=None, tag="s1", tif="DAY", otype="LMT", stop=None):
    return b.place(OrderRequest(client_tag=tag, symbol="AAPL", side="SELL", qty=qty, order_type=otype,
                                limit_price=limit, stop_price=stop, tif=tif))


def test_marketable_buy_fills_and_moves_cash():
    b = mk()
    st = buy(b, 2, 100.2)
    assert st.state == "filled" and st.avg_fill_price == pytest.approx(100.1)
    a = b.account()
    comm = 0.36                                    # 0.35 min + 0.0032*2 pass-through, rounded to cents
    assert a.total_cash == pytest.approx(1000 - 200.2 - comm, abs=0.01)
    assert a.settled_cash == a.total_cash
    assert a.net_liquidation == pytest.approx(1000 - 0.2 - comm, abs=0.01)   # marked at last=100
    pos = b.positions()[0]
    assert pos.qty == 2 and pos.avg_cost == pytest.approx((200.2 + comm) / 2, abs=0.001)
    assert b.fills_since(T0)[0].commission == pytest.approx(comm, abs=0.005)


def test_non_marketable_rests_then_fills_on_quote_move():
    b = mk()
    st = buy(b, 1, 99.0)
    assert st.state == "submitted" and len(b.open_orders()) == 1
    b.set_quote("AAPL", bid=98.5, ask=98.9, last=98.7)
    assert not b.open_orders() and b.positions()[0].qty == 1
    assert b.fills_since(T0)[0].price == pytest.approx(98.9)


def test_settled_cash_gate_and_t1_settlement():
    b = mk(cash=300.0)
    assert buy(b, 2, 100.2).state == "filled"
    st = sell(b, 2, 99.8)   # proceeds unsettled until next business day
    assert st.state == "filled"
    a = b.account()
    assert a.total_cash > 290 and a.settled_cash < 100   # ~99.3 settled left after buy
    rej = buy(b, 2, 100.2, tag="t2")
    assert rej.state == "rejected" and "insufficient settled cash" in rej.reason
    b.set_time(T0 + timedelta(days=1))                    # Tuesday: settled
    a2 = b.account()
    assert a2.settled_cash == pytest.approx(a2.total_cash)
    assert buy(b, 2, 100.2, tag="t3").state == "filled"


def test_settlement_skips_weekend():
    b = mk()
    b.set_time(datetime(2026, 1, 9, 15, 0, tzinfo=timezone.utc))   # Friday
    buy(b, 1, 100.2)
    sell(b, 1, 99.8)
    b.set_time(datetime(2026, 1, 10, 15, 0, tzinfo=timezone.utc))  # Saturday
    a = b.account()
    assert a.settled_cash < a.total_cash - 90
    b.set_time(datetime(2026, 1, 12, 15, 0, tzinfo=timezone.utc))  # Monday
    a = b.account()
    assert a.settled_cash == pytest.approx(a.total_cash)


def test_no_shorting_and_reserved_quantity():
    b = mk()
    buy(b, 2, 100.2)
    assert sell(b, 3, 99.8).state == "rejected"
    st = sell(b, 2, 105.0, tag="s-rest")            # rests
    assert st.state == "submitted"
    assert sell(b, 1, 99.8, tag="s2").state == "rejected"   # reserved by the resting sell


def test_gtc_stop_survives_day_roll_and_gap_fills_below_stop():
    b = mk()
    buy(b, 2, 100.2)
    st = sell(b, 2, tag="stop", tif="GTC", otype="STP", stop=95.0)
    assert st.state == "submitted"
    b.set_time(T0 + timedelta(days=1))
    assert [o.client_tag for o in b.open_orders()] == ["stop"]
    b.mark("AAPL", 96.0)
    assert b.open_orders()                            # not hit
    b.mark("AAPL", 93.0)                              # gap through the stop
    fills = b.fills_since(T0)
    assert fills[-1].client_tag == "stop" and fills[-1].price == pytest.approx(93.0)
    assert not b.positions()


def test_stop_limit_rests_after_trigger_until_price_recovers():
    b = mk()
    buy(b, 2, 100.2)
    sell(b, 2, limit=94.0, tag="stl", tif="GTC", otype="STP LMT", stop=95.0)
    b.mark("AAPL", 93.0)          # triggered, but bid 92.99 < limit 94 -> rests
    assert b.open_orders() and b.positions()
    b.mark("AAPL", 94.5)          # bid 94.499 >= 94 -> fills at max(limit, bid) = bid
    assert not b.open_orders()
    assert b.fills_since(T0)[-1].price == pytest.approx(94.4906, abs=0.01)


def test_day_orders_expire_and_cancel():
    b = mk()
    buy(b, 1, 90.0, tag="day")
    st = buy(b, 1, 90.0, tag="gtc", tif="GTC")
    b.set_time(T0 + timedelta(days=1))
    assert [o.client_tag for o in b.open_orders()] == ["gtc"]
    b.cancel(st.broker_order_id)
    assert not b.open_orders()
    with pytest.raises(SimError):
        b.cancel("999")


def test_market_order_and_rejections():
    b = mk()
    assert buy(b, 1, None, otype="MKT").state == "filled"
    assert buy(b, 1, None).state == "rejected"                    # LMT without price
    assert buy(b, 0, 100.0).state == "rejected"
    r = b.place(OrderRequest(client_tag="x", symbol="MSFT", side="BUY", qty=1, order_type="MKT"))
    assert r.state == "rejected" and "no market data" in r.reason
    with pytest.raises(SimError):
        b.quote(Contract("MSFT"))
    with pytest.raises(SimError):
        b.set_time(T0 - timedelta(days=1))


def test_bars_and_quote_snapshot():
    b = mk()
    bars = [Bar(T0 - timedelta(days=i), 100, 101, 99, 100, 1e6) for i in range(40, 0, -1)]
    b.set_bars("AAPL", bars)
    assert len(b.daily_bars(AAPL, 20)) == 20
    q = b.quote(AAPL)
    assert q.mid == pytest.approx(100.0) and q.ts == T0
