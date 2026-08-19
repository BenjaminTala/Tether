"""Shadow fleet: live data proxied, money simulated, variants loadable, learnings shared."""
from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from ibagent.broker.base import Contract, OrderRequest
from ibagent.broker.shadow import ShadowBroker
from ibagent.broker.sim import SimBroker, SimConfig
from ibagent.config import load_mandate
from tests.conftest import NOW, make_quote

REPO = Path(__file__).resolve().parents[1]


class FakeData:
    """Stands in for IBKRBroker: serves quotes, never sees orders."""

    def __init__(self):
        self.connected = False
        self.quotes = {}
        self.order_calls = 0

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def is_connected(self):
        return self.connected

    def quote(self, contract):
        return self.quotes[contract.symbol]

    def daily_bars(self, contract, days):
        return []


def make_shadow(cash=10_000.0):
    data = FakeData()
    sim = SimBroker(SimConfig(initial_cash=cash))
    clock = {"now": NOW}
    sb = ShadowBroker(data, sim, now_fn=lambda: clock["now"])
    sb.connect()
    return data, sim, sb, clock


def test_orders_go_to_sim_never_to_data_broker():
    data, sim, sb, clock = make_shadow()
    data.quotes["QQQ"] = make_quote("QQQ", 100)
    sb.quote(Contract(symbol="QQQ"))                       # proxied AND primes the sim
    st = sb.place(OrderRequest(client_tag="t1", symbol="QQQ", side="BUY", qty=2,
                               order_type="LMT", limit_price=100.10))
    assert st.state == "filled"
    assert sb.positions()[0].qty == 2
    assert data.order_calls == 0                           # the real broker never sees money
    assert sb.account().net_liquidation == pytest.approx(10_000, abs=5)


def test_gtc_stop_fires_on_fresh_quote():
    data, sim, sb, clock = make_shadow()
    data.quotes["QQQ"] = make_quote("QQQ", 100)
    sb.quote(Contract(symbol="QQQ"))
    sb.place(OrderRequest(client_tag="b", symbol="QQQ", side="BUY", qty=1,
                          order_type="LMT", limit_price=100.10))
    sb.place(OrderRequest(client_tag="s", symbol="QQQ", side="SELL", qty=1,
                          order_type="STP", stop_price=95.0, tif="GTC"))
    clock["now"] = NOW + timedelta(minutes=30)
    data.quotes["QQQ"] = make_quote("QQQ", 93.0, ts=clock["now"])
    sb.quote(Contract(symbol="QQQ"))                       # gap through the stop -> sim matches
    fills = [f for f in sb.fills_since(NOW) if f.client_tag == "s"]
    assert len(fills) == 1 and fills[0].price <= 95.0


def test_shadow_variant_configs_load():
    for spec_path in sorted((REPO / "shadows").glob("*.yaml")):
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        m = load_mandate(REPO / "mandate.yaml", dict(spec["overrides"]))
        assert m.mode == "paper"
        total = (m.sleeves.core.weight + m.sleeves.trend.weight
                 + m.sleeves.spec.weight + m.sleeves.cash.weight)
        assert total == pytest.approx(1.0)
        assert m.broker.client_id != 17, f"{spec_path.name}: must not collide with the main agent"
        assert m.alerts.channels == ["stdout"], f"{spec_path.name}: shadows must not spam Telegram"
        assert "data-shadows" in m.journal.dir
