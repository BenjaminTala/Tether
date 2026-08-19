"""ShadowBroker: live market data, simulated money.

Composes the real IBKRBroker (quotes/bars via its own API client id on the same Gateway
login) with the deterministic SimBroker (orders, fills, stops, T+1 settled cash). This lets
any number of parallel agent variants trade the SAME live market with fake cash — the
"shadow fleet" — while the primary agent alone talks to the real paper account.

Every quote proxied to the caller is also pushed into the simulator, so resting stop/limit
orders in the sim match against fresh real prices whenever the supervisor looks at the
market (fast loop during RTH). Between looks the GAPS are honored: a stop crossed while
nobody was polling fills at the crossing price on the next quote, as in reality.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, List

from ibagent.broker.base import (AccountSnapshot, Bar, Contract, Fill, OrderRequest,
                                 OrderStatus, Position, Quote)
from ibagent.broker.sim import SimBroker


class ShadowBroker:
    def __init__(self, data_broker, sim: SimBroker,
                 now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.data = data_broker
        self.sim = sim
        self._now_fn = now_fn

    # ------------------------------------------------------------------ lifecycle -> data feed
    def connect(self) -> None:
        self.data.connect()
        self.sim.connect()

    def disconnect(self) -> None:
        self.data.disconnect()

    def is_connected(self) -> bool:
        return self.data.is_connected()

    # ------------------------------------------------------------------ market data -> proxied
    def quote(self, contract: Contract) -> Quote:
        self._tick()
        q = self.data.quote(contract)
        try:
            if q.bid and q.ask and q.bid > 0 and q.ask >= q.bid:
                self.sim.set_quote(q.symbol, q.bid, q.ask, last=q.last or None)
            elif q.last and q.last > 0:
                self.sim.mark(q.symbol, q.last)            # closed market: synthesize a spread
        except Exception:
            pass                                           # a bad tick must not break the read
        return q

    def daily_bars(self, contract: Contract, days: int) -> List[Bar]:
        return self.data.daily_bars(contract, days)

    # ------------------------------------------------------------------ money -> simulated
    def account(self) -> AccountSnapshot:
        self._tick()
        return self.sim.account()

    def positions(self) -> List[Position]:
        return self.sim.positions()

    def open_orders(self) -> List[OrderStatus]:
        return self.sim.open_orders()

    def place(self, req: OrderRequest) -> OrderStatus:
        self._tick()
        return self.sim.place(req)

    def cancel(self, broker_order_id: str) -> None:
        self.sim.cancel(broker_order_id)

    def fills_since(self, ts: datetime) -> List[Fill]:
        return self.sim.fills_since(ts)

    # ------------------------------------------------------------------ internals
    def _tick(self) -> None:
        now = self._now_fn()
        if now > self.sim.now:
            self.sim.set_time(now)
