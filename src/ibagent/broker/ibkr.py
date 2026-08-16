"""IBKR adapter over ib_async, implementing broker.base.Broker.

Single-threaded by design: call it only from the supervisor thread (ib_async runs an asyncio
loop under the hood; use `broker.sleep()` — never time.sleep() — to let messages flow).

Identity of orders: `broker_order_id` is IBKR's permId once acknowledged (stable across
sessions, which matters for GTC stops placed by a previous run), else "o<orderId>". The engine's
own idempotency key travels in `orderRef` (client_tag) and comes back on open orders and fills.

Pure helper functions (build_order, map_status, parse_account_values, to_ib_stock, bar/fill
mappers) are tested without a Gateway; the connection paths are exercised by `ibagent broker smoke`.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence

from ibagent.broker.base import (AccountSnapshot, Bar, Contract, Fill, OrderRequest, OrderState, OrderStatus,
                                 Position, Quote)
from ibagent.config import BrokerCfg
from ibagent.marketclock import utc

try:  # keep the module importable without ib_async so tests of the rest of the engine don't need it
    from ib_async import IB, LimitOrder, MarketOrder, Order, Stock, StopLimitOrder, StopOrder
    from ib_async import Contract as IBContract
    from ib_async import Trade
    from ib_async.objects import AccountValue, BarData
    from ib_async.objects import Fill as IBFill
except ImportError:  # pragma: no cover
    IB = LimitOrder = MarketOrder = Order = Stock = StopLimitOrder = StopOrder = IBContract = Trade = None  # type: ignore
    AccountValue = BarData = IBFill = None  # type: ignore

log = logging.getLogger(__name__)

_STATUS_MAP: Dict[str, OrderState] = {
    "PendingSubmit": "pending", "ApiPending": "pending",
    "PreSubmitted": "submitted", "Submitted": "submitted", "PendingCancel": "submitted",
    "Filled": "filled", "Cancelled": "cancelled", "ApiCancelled": "cancelled", "Inactive": "rejected",
}
_ACTIVE = ("pending", "submitted", "partially_filled")


class BrokerError(RuntimeError):
    """Connectivity, contract or account problems (not order rejections — those come back as status)."""


# ----------------------------------------------------------------------------- pure helpers


def _clean(x: object) -> Optional[float]:
    try:
        f = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or f <= 0 else f


def to_ib_stock(c: Contract) -> "Stock":
    return Stock(c.symbol, c.exchange or "SMART", c.currency or "USD")


def build_order(req: OrderRequest, qty_precision: int = 4) -> "Order":
    qty = round(float(req.qty), qty_precision)
    if qty <= 0:
        raise BrokerError(f"{req.client_tag}: quantity rounds to zero")
    if req.order_type in ("LMT", "STP LMT") and not req.limit_price:
        raise BrokerError(f"{req.client_tag}: limit price required")
    if req.order_type in ("STP", "STP LMT") and not req.stop_price:
        raise BrokerError(f"{req.client_tag}: stop price required")
    lmt = round(float(req.limit_price), 2) if req.limit_price else None
    stp = round(float(req.stop_price), 2) if req.stop_price else None
    if req.order_type == "LMT":
        o = LimitOrder(req.side, qty, lmt)
    elif req.order_type == "MKT":
        o = MarketOrder(req.side, qty)
    elif req.order_type == "STP":
        o = StopOrder(req.side, qty, stp)
    elif req.order_type == "STP LMT":
        o = StopLimitOrder(req.side, qty, lmt, stp)
    else:
        raise BrokerError(f"unsupported order type {req.order_type}")
    o.tif = req.tif
    o.outsideRth = bool(req.outside_rth)
    o.orderRef = req.client_tag[:80]
    o.transmit = True
    return o


def map_status(ib_status: str, filled: float, remaining: float) -> OrderState:
    state = _STATUS_MAP.get(ib_status, "unknown")
    if state == "submitted" and filled > 0 and remaining > 0:
        return "partially_filled"
    return state


def order_id_of(order: "Order") -> str:
    perm = getattr(order, "permId", 0) or 0
    return str(perm) if perm > 0 else f"o{order.orderId}"


def trade_to_status(trade: "Trade") -> OrderStatus:
    os_ = trade.orderStatus
    filled, remaining = float(os_.filled or 0), float(os_.remaining or 0)
    reason = " | ".join(e.message for e in trade.log if getattr(e, "message", ""))[-300:]
    ts = trade.log[-1].time if trade.log else None
    return OrderStatus(broker_order_id=order_id_of(trade.order), client_tag=trade.order.orderRef or "",
                       symbol=trade.contract.symbol, side=trade.order.action,
                       state=map_status(os_.status, filled, remaining), qty=float(trade.order.totalQuantity),
                       filled_qty=filled, avg_fill_price=_clean(os_.avgFillPrice),
                       ts=utc(ts) if ts else None, reason=reason)


def parse_account_values(values: Iterable["AccountValue"], base_currency: str, ts: datetime) -> AccountSnapshot:
    picked: Dict[str, Dict[str, float]] = {}
    for v in values:
        if v.tag not in ("NetLiquidation", "TotalCashValue", "SettledCash"):
            continue
        try:
            picked.setdefault(v.tag, {})[v.currency] = float(v.value)
        except (TypeError, ValueError):
            continue

    def pick(tag: str) -> Optional[float]:
        by_ccy = picked.get(tag, {})
        for ccy in (base_currency, "BASE"):
            if ccy in by_ccy:
                return by_ccy[ccy]
        return next(iter(by_ccy.values()), None)

    net, cash, settled = pick("NetLiquidation"), pick("TotalCashValue"), pick("SettledCash")
    if net is None or cash is None:
        raise BrokerError("account values incomplete (NetLiquidation/TotalCashValue missing)")
    if settled is None:
        log.warning("SettledCash missing from account values; falling back to TotalCashValue")
        settled = cash
    return AccountSnapshot(ts=ts, net_liquidation=round(net, 2), total_cash=round(cash, 2),
                           settled_cash=round(settled, 2), currency=base_currency)


def bar_from_ib(b: "BarData") -> Bar:
    d = b.date
    if isinstance(d, datetime):
        ts = utc(d)
    elif isinstance(d, date):
        ts = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    else:
        ts = utc(datetime.strptime(str(d)[:8], "%Y%m%d"))
    return Bar(ts=ts, open=float(b.open), high=float(b.high), low=float(b.low), close=float(b.close),
               volume=float(b.volume))


def fill_from_ib(f: "IBFill") -> Fill:
    ex = f.execution
    comm = getattr(f.commissionReport, "commission", 0.0) or 0.0
    return Fill(broker_order_id=str(ex.permId) if ex.permId else f"o{ex.orderId}",
                client_tag=ex.orderRef or "", symbol=f.contract.symbol,
                side="BUY" if ex.side == "BOT" else "SELL", qty=float(ex.shares), price=float(ex.price),
                commission=0.0 if math.isnan(comm) else float(comm), ts=utc(f.time))


def duration_str(days: int) -> str:
    if days <= 0:
        raise ValueError("days must be positive")
    return f"{days} D" if days <= 365 else f"{math.ceil(days / 365)} Y"


# ----------------------------------------------------------------------------- adapter


class IBKRBroker:
    def __init__(self, cfg: BrokerCfg, account_id: str = "", base_currency: str = "USD",
                 ib: Optional["IB"] = None, qty_precision: int = 4, ack_wait_s: float = 1.5,
                 quote_timeout_s: float = 8.0):
        if IB is None and ib is None:
            raise BrokerError("ib_async is not installed (pip install ib_async)")
        self.cfg = cfg
        self.account_id = account_id
        self.base_currency = base_currency
        self.ib = ib or IB()
        self.qty_precision = qty_precision
        self.ack_wait_s = ack_wait_s
        self.quote_timeout_s = quote_timeout_s
        self._contracts: Dict[str, "IBContract"] = {}

    # ---- connection ----
    def connect(self, attempts: int = 3) -> None:
        last: Optional[BaseException] = None
        for i in range(attempts):
            try:
                self.ib.connect(self.cfg.host, self.cfg.port, clientId=self.cfg.client_id,
                                timeout=self.cfg.connect_timeout_s, readonly=False, account=self.account_id)
                self.ib.reqMarketDataType(self.cfg.market_data_type)
                managed = self.ib.managedAccounts()
                if self.account_id and managed and self.account_id not in managed:
                    self.ib.disconnect()
                    raise BrokerError(f"account {self.account_id} not among managed accounts {managed}")
                log.info("connected to IB %s:%s clientId=%s accounts=%s", self.cfg.host, self.cfg.port,
                         self.cfg.client_id, managed)
                return
            except BrokerError:
                raise
            except (OSError, TimeoutError, ConnectionError, RuntimeError) as exc:
                last = exc
                log.warning("IB connect attempt %d/%d failed: %s", i + 1, attempts, exc)
                self.sleep(2.0 * (i + 1))
        raise BrokerError(f"cannot connect to IB Gateway at {self.cfg.host}:{self.cfg.port}: {last}")

    def disconnect(self) -> None:
        if self.ib.isConnected():
            self.ib.disconnect()

    def is_connected(self) -> bool:
        return bool(self.ib.isConnected())

    def sleep(self, seconds: float) -> None:
        """Yield to the ib_async event loop (also usable while disconnected)."""
        self.ib.sleep(seconds)

    # ---- account / positions / orders ----
    def account(self) -> AccountSnapshot:
        vals = self.ib.accountValues(self.account_id)
        if not vals:
            self.sleep(1.0)
            vals = self.ib.accountValues(self.account_id)
        return parse_account_values(vals, self.base_currency, datetime.now(timezone.utc))

    def positions(self) -> List[Position]:
        out = []
        for p in self.ib.positions(self.account_id):
            if p.contract.secType != "STK" or not p.position:
                continue
            out.append(Position(symbol=p.contract.symbol, qty=float(p.position), avg_cost=float(p.avgCost)))
        return sorted(out, key=lambda x: x.symbol)

    def open_orders(self) -> List[OrderStatus]:
        trades = self.ib.reqAllOpenOrders()
        return [s for s in (trade_to_status(t) for t in trades) if s.state in _ACTIVE]

    def place(self, req: OrderRequest) -> OrderStatus:
        contract = self._qualify(req.contract or Contract(symbol=req.symbol))
        order = build_order(req, self.qty_precision)
        trade = self.ib.placeOrder(contract, order)
        self.sleep(self.ack_wait_s)
        status = trade_to_status(trade)
        if status.state == "rejected" and not status.reason:
            status.reason = "rejected by IBKR (see Gateway log)"
        return status

    def cancel(self, broker_order_id: str) -> None:
        trade = self._find_trade(broker_order_id)
        if trade is None:
            raise BrokerError(f"open order {broker_order_id} not found")
        self.ib.cancelOrder(trade.order)
        self.sleep(0.5)

    def fills_since(self, ts: datetime) -> List[Fill]:
        ts = utc(ts)
        seen: Dict[str, Fill] = {}
        for f in list(self.ib.fills()) + list(self.ib.reqExecutions()):
            if f.execution.execId in seen:
                continue
            if utc(f.time) >= ts:
                seen[f.execution.execId] = fill_from_ib(f)
        return sorted(seen.values(), key=lambda x: x.ts)

    # ---- market data ----
    def quote(self, contract: Contract) -> Quote:
        c = self._qualify(contract)
        delayed = self.cfg.market_data_type != 1
        tickers = self.ib.reqTickers(c)
        t = tickers[0] if tickers else None
        bid, ask, last = (_clean(t.bid), _clean(t.ask), _clean(t.last)) if t else (None, None, None)
        if bid is None and ask is None and last is None:
            bid, ask, last = self._stream_quote(c)
        if bid is None and ask is None and last is None:
            close = _clean(t.close) if t else None
            if close is None:
                raise BrokerError(f"no market data for {contract.symbol} (check data permissions / RTH)")
            last = close
        return Quote(symbol=contract.symbol, bid=bid, ask=ask, last=last, ts=datetime.now(timezone.utc), delayed=delayed)

    def daily_bars(self, contract: Contract, days: int) -> List[Bar]:
        c = self._qualify(contract)
        bars = self.ib.reqHistoricalData(c, endDateTime="", durationStr=duration_str(days), barSizeSetting="1 day",
                                         whatToShow="TRADES", useRTH=True, formatDate=1)
        out = [bar_from_ib(b) for b in bars]
        if not out:
            raise BrokerError(f"no historical bars for {contract.symbol}")
        return out[-days:]

    # ---- internals ----
    def _qualify(self, contract: Contract) -> "IBContract":
        key = f"{contract.symbol}|{contract.exchange}|{contract.currency}"
        if key in self._contracts:
            return self._contracts[key]
        stock = to_ib_stock(contract)
        details = self.ib.reqContractDetails(stock)
        if not details:
            raise BrokerError(f"unknown contract {contract}")
        if len(details) > 1:
            same_ccy = [d for d in details if d.contract.currency == (contract.currency or "USD")]
            details = same_ccy or details
            log.warning("ambiguous contract %s: %d matches, using %s", contract.symbol, len(details),
                        details[0].contract.primaryExchange)
        self._contracts[key] = details[0].contract
        return details[0].contract

    def _find_trade(self, broker_order_id: str) -> Optional["Trade"]:
        for t in list(self.ib.openTrades()) + list(self.ib.reqAllOpenOrders()):
            if order_id_of(t.order) == broker_order_id or f"o{t.order.orderId}" == broker_order_id \
                    or (t.order.permId and str(t.order.permId) == broker_order_id):
                return t
        return None

    def _stream_quote(self, c: "IBContract"):
        t = self.ib.reqMktData(c, "", False, False)
        try:
            waited = 0.0
            while waited < self.quote_timeout_s:
                self.sleep(0.5)
                waited += 0.5
                bid, ask, last = _clean(t.bid), _clean(t.ask), _clean(t.last)
                if bid or ask or last:
                    return bid, ask, last
            return None, None, None
        finally:
            self.ib.cancelMktData(c)
