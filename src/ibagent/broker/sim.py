"""Deterministic in-memory broker implementing broker.base.Broker (tests, dry runs, replays).

Fill model
  LMT      BUY fills iff limit >= ask, at min(limit, ask*(1+slip)); SELL iff limit <= bid, at
           max(limit, bid*(1-slip)); otherwise rests and is re-checked on every mark/quote update.
  MKT      fills immediately at ask/bid with slippage.
  STP      rests; when a mark crosses the stop it fills at min(stop, price) for SELL and
           max(stop, price) for BUY — gaps hurt, as in reality.
  STP LMT  on trigger becomes a resting LMT at its limit price.
  DAY orders expire when the simulated date rolls forward; GTC orders persist.

Cash account
  total cash moves at fill time; settled cash decreases at BUY fills and increases for SELL
  proceeds only after `settlement_days` business days. BUYs require settled cash when
  `enforce_settled_cash`. No shorting: SELL qty may not exceed the unreserved position.

Not thread-safe by design (the engine is single-threaded).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple

from ibagent.broker.base import (AccountSnapshot, Bar, Contract, Fill, OrderRequest, OrderStatus, Position, Quote)
from ibagent.fees import CommissionModel, estimate_commission
from ibagent.marketclock import add_business_days, utc


class SimError(RuntimeError):
    """Programming errors in test setup (missing quote/bars), never used for order rejections."""


@dataclass
class SimConfig:
    initial_cash: float = 1_000.0
    commission_model: CommissionModel = "tiered"
    slippage_bps: float = 2.0
    settlement_days: int = 1
    enforce_settled_cash: bool = True
    currency: str = "USD"
    qty_precision: int = 4


@dataclass
class _Order:
    req: OrderRequest
    status: OrderStatus
    created: datetime
    triggered: bool = False           # STP / STP LMT trigger state


class SimBroker:
    def __init__(self, cfg: Optional[SimConfig] = None, now: Optional[datetime] = None):
        self.cfg = cfg or SimConfig()
        self._now = utc(now or datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc))
        self._connected = False
        self._quotes: Dict[str, Quote] = {}
        self._bars: Dict[str, List[Bar]] = {}
        self._positions: Dict[str, Tuple[float, float]] = {}      # symbol -> (qty, avg_cost)
        self._orders: Dict[str, _Order] = {}
        self._fills: List[Fill] = []
        self._total_cash = float(self.cfg.initial_cash)
        self._settled_cash = float(self.cfg.initial_cash)
        self._pending: List[Tuple[date, float]] = []                # (settle_date, amount)
        self._next_id = 1

    # ------------------------------------------------------------------ test/replay controls
    @property
    def now(self) -> datetime:
        return self._now

    def set_time(self, now: datetime) -> None:
        now = utc(now)
        if now < self._now:
            raise SimError("time cannot go backwards")
        rolled = now.date() != self._now.date()
        self._now = now
        if rolled:
            self._expire_day_orders()
        self._settle()

    def set_quote(self, symbol: str, bid: float, ask: float, last: Optional[float] = None) -> None:
        if bid <= 0 or ask <= 0 or ask < bid:
            raise SimError(f"bad quote for {symbol}: bid={bid} ask={ask}")
        self._quotes[symbol] = Quote(symbol=symbol, bid=bid, ask=ask, last=last if last else (bid + ask) / 2,
                                     ts=self._now, delayed=False)
        self._match_resting(symbol)

    def mark(self, symbol: str, price: float, spread_bps: float = 2.0) -> None:
        """Move the market to `price` (bid/ask around it) and process resting orders."""
        half = price * spread_bps / 20_000.0
        self.set_quote(symbol, round(price - half, 4), round(price + half, 4), last=price)

    def set_bars(self, symbol: str, bars: List[Bar]) -> None:
        self._bars[symbol] = sorted(bars, key=lambda b: b.ts)

    def force_position(self, symbol: str, qty: float, avg_cost: float) -> None:
        """Seed a pre-existing position (e.g. reconciliation tests)."""
        self._positions[symbol] = (qty, avg_cost)

    # ------------------------------------------------------------------ Broker protocol
    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def account(self) -> AccountSnapshot:
        self._settle()
        mv = sum(qty * self._mark_price(sym) for sym, (qty, _) in self._positions.items() if qty)
        return AccountSnapshot(ts=self._now, net_liquidation=round(self._total_cash + mv, 2),
                               total_cash=round(self._total_cash, 2), settled_cash=round(self._settled_cash, 2),
                               currency=self.cfg.currency)

    def positions(self) -> List[Position]:
        return [Position(symbol=s, qty=q, avg_cost=c) for s, (q, c) in sorted(self._positions.items()) if q]

    def open_orders(self) -> List[OrderStatus]:
        return [replace(o.status) for o in self._orders.values() if o.status.state in ("submitted", "partially_filled")]

    def quote(self, contract: Contract) -> Quote:
        q = self._quotes.get(contract.symbol)
        if q is None:
            raise SimError(f"no quote for {contract.symbol}")
        return replace(q, ts=self._now)

    def daily_bars(self, contract: Contract, days: int) -> List[Bar]:
        bars = self._bars.get(contract.symbol)
        if bars is None:
            raise SimError(f"no bars for {contract.symbol}")
        return [b for b in bars if b.ts <= self._now][-days:]

    def place(self, req: OrderRequest) -> OrderStatus:
        oid = str(self._next_id)
        self._next_id += 1
        qty = round(req.qty, self.cfg.qty_precision)
        status = OrderStatus(broker_order_id=oid, client_tag=req.client_tag, symbol=req.symbol, side=req.side,
                             state="submitted", qty=qty, ts=self._now)
        order = _Order(req=replace(req, qty=qty), status=status, created=self._now)
        reason = self._reject_reason(order)
        if reason:
            status.state, status.reason = "rejected", reason
            self._orders[oid] = order
            return replace(status)
        self._orders[oid] = order
        self._try_fill(order)
        return replace(order.status)

    def cancel(self, broker_order_id: str) -> None:
        o = self._orders.get(broker_order_id)
        if o is None:
            raise SimError(f"unknown order {broker_order_id}")
        if o.status.state in ("submitted", "partially_filled"):
            o.status.state, o.status.reason, o.status.ts = "cancelled", "cancelled by client", self._now

    def fills_since(self, ts: datetime) -> List[Fill]:
        ts = utc(ts)
        return [f for f in self._fills if f.ts >= ts]

    # ------------------------------------------------------------------ internals
    def _reject_reason(self, o: _Order) -> str:
        r = o.req
        if r.qty <= 0:
            return "quantity must be positive"
        if r.symbol not in self._quotes:
            return f"no market data for {r.symbol}"
        if r.order_type in ("LMT", "STP LMT") and not r.limit_price:
            return "limit price required"
        if r.order_type in ("STP", "STP LMT") and not r.stop_price:
            return "stop price required"
        if r.side == "SELL":
            held = self._positions.get(r.symbol, (0.0, 0.0))[0]
            reserved = sum(x.req.qty for x in self._orders.values()
                           if x.req.symbol == r.symbol and x.req.side == "SELL"
                           and x.status.state in ("submitted", "partially_filled"))
            if r.qty > held - reserved + 1e-9:
                return "insufficient position (no shorting)"
        else:
            q = self._quotes[r.symbol]
            est_price = r.limit_price or q.ask
            need = r.qty * est_price + estimate_commission(self.cfg.commission_model, r.qty, est_price, "BUY")
            avail = self._settled_cash if self.cfg.enforce_settled_cash else self._total_cash
            if need > avail + 1e-9:
                kind = "settled cash" if self.cfg.enforce_settled_cash else "cash"
                return f"insufficient {kind}: need {need:.2f}, have {avail:.2f}"
        return ""

    def _match_resting(self, symbol: str) -> None:
        for o in list(self._orders.values()):
            if o.req.symbol == symbol and o.status.state == "submitted":
                self._try_fill(o)

    def _try_fill(self, o: _Order) -> None:
        r, q = o.req, self._quotes[o.req.symbol]
        slip = self.cfg.slippage_bps / 10_000.0
        price: Optional[float] = None
        if r.order_type == "MKT":
            price = q.ask * (1 + slip) if r.side == "BUY" else q.bid * (1 - slip)
        elif r.order_type == "LMT" or (r.order_type == "STP LMT" and o.triggered):
            lmt = float(r.limit_price)  # presence validated at placement
            if r.side == "BUY" and lmt >= q.ask:
                price = min(lmt, q.ask * (1 + slip))
            elif r.side == "SELL" and lmt <= q.bid:
                price = max(lmt, q.bid * (1 - slip))
        elif r.order_type in ("STP", "STP LMT") and not o.triggered:
            stop, last = float(r.stop_price), float(q.last)
            hit = last <= stop if r.side == "SELL" else last >= stop
            if hit:
                o.triggered = True
                if r.order_type == "STP":
                    price = min(stop, last) * (1 - slip) if r.side == "SELL" else max(stop, last) * (1 + slip)
                else:
                    self._try_fill(o)   # now behaves as a resting LMT
                    return
        if price is None:
            return
        self._fill(o, round(price, 4))

    def _fill(self, o: _Order, price: float) -> None:
        r = o.req
        comm = estimate_commission(self.cfg.commission_model, r.qty, price, r.side)
        notional = r.qty * price
        qty, avg = self._positions.get(r.symbol, (0.0, 0.0))
        if r.side == "BUY":
            new_qty = qty + r.qty
            avg = (qty * avg + notional + comm) / new_qty
            self._positions[r.symbol] = (round(new_qty, 8), round(avg, 6))
            self._total_cash -= notional + comm
            self._settled_cash -= notional + comm
        else:
            new_qty = round(qty - r.qty, 8)
            self._positions[r.symbol] = (new_qty, avg if new_qty > 0 else 0.0)
            proceeds = notional - comm
            self._total_cash += proceeds
            self._pending.append((add_business_days(self._now.date(), self.cfg.settlement_days), proceeds))
        o.status.state, o.status.filled_qty, o.status.avg_fill_price, o.status.ts = "filled", r.qty, price, self._now
        self._fills.append(Fill(broker_order_id=o.status.broker_order_id, client_tag=r.client_tag, symbol=r.symbol,
                                side=r.side, qty=r.qty, price=price, commission=comm, ts=self._now))

    def _settle(self) -> None:
        today = self._now.date()
        keep: List[Tuple[date, float]] = []
        for settle_date, amount in self._pending:
            if settle_date <= today:
                self._settled_cash += amount
            else:
                keep.append((settle_date, amount))
        self._pending = keep

    def _expire_day_orders(self) -> None:
        for o in self._orders.values():
            if o.req.tif == "DAY" and o.status.state == "submitted" and o.created.date() < self._now.date():
                o.status.state, o.status.reason, o.status.ts = "cancelled", "DAY order expired", self._now

    def _mark_price(self, symbol: str) -> float:
        q = self._quotes.get(symbol)
        if q is None:
            return self._positions.get(symbol, (0.0, 0.0))[1]
        return float(q.last or q.mid or 0.0)
