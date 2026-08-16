"""Broker abstraction. The engine only ever talks to this Protocol.

Implementations: broker/ibkr.py (ib_async, Phase 2), broker/sim.py (deterministic in-memory, Phase 2).
Quantities are floats to support fractional shares; the engine rounds per instrument rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Literal, Optional, Protocol

from ibagent.common import Side

OrderType = Literal["LMT", "MKT", "STP", "STP LMT"]
Tif = Literal["DAY", "GTC"]
OrderState = Literal["pending", "submitted", "partially_filled", "filled", "cancelled", "rejected", "unknown"]


@dataclass(frozen=True)
class Contract:
    symbol: str
    exchange: str = "SMART"
    currency: str = "USD"
    sec_type: str = "STK"


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    ts: datetime
    delayed: bool = True

    @property
    def mid(self) -> Optional[float]:
        if self.bid and self.ask and self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last


@dataclass(frozen=True)
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Position:
    symbol: str
    qty: float
    avg_cost: float


@dataclass(frozen=True)
class AccountSnapshot:
    ts: datetime
    net_liquidation: float
    total_cash: float
    settled_cash: float
    currency: str = "USD"


@dataclass(frozen=True)
class OrderRequest:
    client_tag: str                 # engine's idempotency key, e.g. "w2026-08-17-AAPL-BUY"
    symbol: str
    side: Side
    qty: float
    order_type: OrderType
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    tif: Tif = "DAY"
    outside_rth: bool = False
    contract: Optional[Contract] = None


@dataclass
class OrderStatus:
    broker_order_id: str
    client_tag: str
    symbol: str
    side: Side
    state: OrderState
    qty: float
    filled_qty: float = 0.0
    avg_fill_price: Optional[float] = None
    ts: Optional[datetime] = None
    reason: str = ""


@dataclass(frozen=True)
class Fill:
    broker_order_id: str
    client_tag: str
    symbol: str
    side: Side
    qty: float
    price: float
    commission: float
    ts: datetime


class Broker(Protocol):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def is_connected(self) -> bool: ...
    def account(self) -> AccountSnapshot: ...
    def positions(self) -> List[Position]: ...
    def open_orders(self) -> List[OrderStatus]: ...
    def quote(self, contract: Contract) -> Quote: ...
    def daily_bars(self, contract: Contract, days: int) -> List[Bar]: ...
    def place(self, req: OrderRequest) -> OrderStatus: ...
    def cancel(self, broker_order_id: str) -> None: ...
    def fills_since(self, ts: datetime) -> List[Fill]: ...
