"""Execution: the only code that turns validated intents into broker orders and book fills.

Everything placed here has already passed risk.plan_orders or comes from the deterministic
sleeve engine. This layer:
  * places DAY marketable-limit orders (exits before entries), polls fills, cancels leftovers
  * applies every fill to the Book with its sleeve/meta and journals it
  * keeps the GTC protective stop at the broker in sync (place on entry, tighten-only replace)
  * detects external fills of our stop tags (stop-outs) and applies cooldowns
  * alerts on slippage beyond mandate.execution.slippage_alert_bps

No decisions are made here; a rejected/unfilled order is reported, never retried at a worse
price. Waiting is injectable (`sleeper`) so tests and SimBroker runs complete instantly.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ibagent.alerts import Alerter
from ibagent.book import Book
from ibagent.broker.base import Broker, Contract, Fill, OrderRequest, OrderStatus, Quote
from ibagent.config import Mandate
from ibagent.journal import Journal
from ibagent.risk import Plan, PlannedOrder, StopInstruction
from ibagent.sleeves import ProtectiveAction, RebalanceIntent

FILL_WAIT_S = 90
POLL_INTERVAL_S = 2.0
QTY_DP = 4


@dataclass
class OrderOutcome:
    client_tag: str
    symbol: str
    side: str
    requested_qty: float
    filled_qty: float = 0.0
    avg_price: Optional[float] = None
    state: str = "unfilled"
    reason: str = ""


@dataclass
class ExecutionReport:
    outcomes: List[OrderOutcome] = field(default_factory=list)
    stops_placed: List[str] = field(default_factory=list)      # client tags
    stops_replaced: List[str] = field(default_factory=list)
    realized_pnl: float = 0.0
    errors: List[str] = field(default_factory=list)

    @property
    def filled(self) -> int:
        return sum(1 for o in self.outcomes if o.state == "filled")


class Executor:
    def __init__(self, mandate: Mandate, broker: Broker, book: Book, journal: Journal,
                 alerter: Alerter, sleeper: Callable[[float], None] = time.sleep,
                 now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.m = mandate
        self.broker = broker
        self.book = book
        self.journal = journal
        self.alerter = alerter
        self.sleep = sleeper
        self.now = now_fn
        self._stop_seq = 0

    # ------------------------------------------------------------------ public entry points
    def execute_plan(self, plan: Plan) -> ExecutionReport:
        report = ExecutionReport()
        if plan.hold:
            return report
        stop_by_symbol = {s.symbol: s for s in plan.stop_instructions}
        for po in plan.orders:                                   # exits first (plan is sorted)
            if po.req.side == "SELL":
                self._release_stop(po.req.symbol)                # un-reserve shares held by the GTC stop
            outcome, fills = self._place_and_wait(po.req)
            report.outcomes.append(outcome)
            for f in fills:
                realized = self._apply_fill(f, po)
                report.realized_pnl += realized
            if po.req.side == "SELL" and po.req.symbol not in stop_by_symbol:
                self._restore_stop(po.req.symbol, report)        # trims keep their protection
            if fills and po.req.side == "BUY" and po.req.symbol in stop_by_symbol:
                self._sync_stop(stop_by_symbol.pop(po.req.symbol), report)
        # tighten-only stop updates not tied to a buy (no_change runs, trailing)
        for instr in stop_by_symbol.values():
            self._sync_stop(instr, report)
        self.book.save()
        return report

    def execute_protective(self, actions: Sequence[ProtectiveAction],
                           quotes: Dict[str, Quote]) -> ExecutionReport:
        """Deterministic trade management: partial takes, take-profits, time stops, trails."""
        report = ExecutionReport()
        today = self.now().date()
        for a in actions:
            if a.kind == "trail_stop":
                pos = self.book.positions.get(a.symbol)
                if pos and self.book.tighten_stop(a.symbol, a.new_stop):
                    self._sync_stop(StopInstruction(a.symbol, a.new_stop, pos.qty,
                                                    replaces_tag=pos.stop_order_tag, reason=a.reason),
                                    report, already_tightened=True)
                continue
            pos = self.book.positions.get(a.symbol)
            q = quotes.get(a.symbol)
            if pos is None or q is None:
                report.errors.append(f"{a.symbol}: no position/quote for {a.kind}")
                continue
            lp = self._limit(q, "SELL")
            if lp is None:
                report.errors.append(f"{a.symbol}: no usable quote for {a.kind}")
                continue
            qty = min(pos.qty, a.sell_qty)
            tag = f"p{today.isoformat()}-{a.symbol}-{a.kind[:4].upper()}"
            self._release_stop(a.symbol)
            outcome, fills = self._place_and_wait(OrderRequest(
                client_tag=tag, symbol=a.symbol, side="SELL", qty=qty, order_type="LMT",
                limit_price=lp, tif="DAY", contract=self._contract(a.symbol)))
            outcome.reason = a.reason
            report.outcomes.append(outcome)
            for f in fills:
                report.realized_pnl += self._apply_sell(f, pos.sleeve, reason=f"{a.kind}: {a.reason}")
            still = self.book.positions.get(a.symbol)
            if still is not None:
                if fills and a.kind == "partial_take":
                    still.partial_taken = True
                self._restore_stop(a.symbol, report)
        self.book.save()
        return report

    def execute_rebalance(self, intents: Sequence[RebalanceIntent],
                          quotes: Dict[str, Quote]) -> ExecutionReport:
        report = ExecutionReport()
        today = self.now().date()
        ordered = sorted(intents, key=lambda i: i.side != "SELL")    # sells first free cash
        for it in ordered:
            q = quotes.get(it.symbol)
            if q is None:
                report.errors.append(f"{it.symbol}: no quote for rebalance")
                continue
            lp = self._limit(q, it.side)
            mark = q.mid or q.last
            if lp is None or not mark:
                report.errors.append(f"{it.symbol}: no usable quote for rebalance")
                continue
            qty = round(it.usd / mark, QTY_DP)
            pos = self.book.positions.get(it.symbol)
            if it.side == "SELL":
                qty = min(qty, pos.qty if pos else 0.0)
            if qty <= 0:
                continue
            tag = f"r{today.isoformat()}-{it.symbol}-{it.side}"
            outcome, fills = self._place_and_wait(OrderRequest(
                client_tag=tag, symbol=it.symbol, side=it.side, qty=qty, order_type="LMT",
                limit_price=lp, tif="DAY", contract=self._contract(it.symbol)))
            outcome.reason = it.reason
            report.outcomes.append(outcome)
            for f in fills:
                if f.side == "BUY":
                    self.book.apply_fill(f, "core", self.m.execution.settlement_days,
                                         entry_meta={}, counts_as_new=False)
                    self.journal.record("fill", _fill_payload(f, "core", it.reason))
                else:
                    report.realized_pnl += self._apply_sell(f, "core", reason=it.reason)
        self.book.save()
        return report

    def sync_external_fills(self, since: datetime) -> List[Fill]:
        """Apply fills the engine did not initiate this cycle — above all GTC stop-outs.
        A stop fill closes the position, starts the re-entry cooldown, and alerts."""
        applied: List[Fill] = []
        known = {f.client_tag for f in applied}
        for f in self.broker.fills_since(since):
            pos = self.book.positions.get(f.symbol)
            if pos is None or f.client_tag != pos.stop_order_tag or f.side != "SELL":
                continue
            realized = self._apply_sell(f, pos.sleeve, reason="protective stop fired")
            self.book.record_stop_out(f.symbol, f.ts.date(),
                                      self.m.risk.cooldown_days_after_stop_out)
            self.alerter.warning(f"stop-out {f.symbol}",
                                 f"{f.qty:g} @ {f.price} realized {realized:+.2f}")
            applied.append(f)
        if applied:
            self.book.save()
        return applied

    def cancel_open_engine_orders(self) -> int:
        """Kill switch support: cancel every open order carrying one of our tags."""
        n = 0
        for o in self.broker.open_orders():
            try:
                self.broker.cancel(o.broker_order_id)
                self.journal.record("order_cancelled", {"tag": o.client_tag, "why": "kill switch"})
                n += 1
            except Exception as exc:
                self.journal.record("error", {"where": "cancel", "tag": o.client_tag, "err": str(exc)})
        return n

    # ------------------------------------------------------------------ internals
    def _contract(self, symbol: str) -> Contract:
        inst = self.m.universe.active.instrument(symbol)
        if inst:
            return Contract(symbol=symbol, exchange=inst.exchange, currency=inst.currency)
        return Contract(symbol=symbol)

    def _limit(self, q: Quote, side: str) -> Optional[float]:
        off = self.m.execution.limit_offset_bps / 10_000.0
        ref = (q.ask if side == "BUY" else q.bid) or q.last
        if not ref or ref <= 0:
            return None
        return round(ref * (1 + off) if side == "BUY" else ref * (1 - off), 2)

    def _place_and_wait(self, req: OrderRequest) -> Tuple[OrderOutcome, List[Fill]]:
        req = req if req.contract else OrderRequest(**{**req.__dict__, "contract": self._contract(req.symbol)})
        outcome = OrderOutcome(client_tag=req.client_tag, symbol=req.symbol, side=req.side,
                               requested_qty=req.qty)
        started = self.now()
        self.journal.record("order_placed", {
            "tag": req.client_tag, "symbol": req.symbol, "side": req.side, "qty": req.qty,
            "type": req.order_type, "limit": req.limit_price, "stop": req.stop_price, "tif": req.tif})
        try:
            status = self.broker.place(req)
        except Exception as exc:
            outcome.state, outcome.reason = "error", str(exc)
            self.journal.record("order_error", {"tag": req.client_tag, "err": str(exc)})
            return outcome, []
        if status.state == "rejected":
            outcome.state, outcome.reason = "rejected", status.reason
            self.journal.record("order_rejected", {"tag": req.client_tag, "reason": status.reason})
            return outcome, []
        fills = self._collect_fills(req.client_tag, started)
        waited = 0.0
        while not fills and waited < FILL_WAIT_S:
            self.sleep(POLL_INTERVAL_S)
            waited += POLL_INTERVAL_S
            fills = self._collect_fills(req.client_tag, started)
        if not fills:
            try:
                self.broker.cancel(status.broker_order_id)
            except Exception:
                pass
            outcome.state, outcome.reason = "unfilled", f"no fill in {FILL_WAIT_S}s; cancelled"
            self.journal.record("order_unfilled", {"tag": req.client_tag})
            return outcome, []
        outcome.filled_qty = round(sum(f.qty for f in fills), 8)
        outcome.avg_price = round(sum(f.qty * f.price for f in fills) / outcome.filled_qty, 4)
        outcome.state = "filled" if outcome.filled_qty >= req.qty - 1e-6 else "partial"
        self._check_slippage(req, outcome.avg_price)
        return outcome, fills

    def _collect_fills(self, tag: str, since: datetime) -> List[Fill]:
        try:
            return [f for f in self.broker.fills_since(since) if f.client_tag == tag]
        except Exception:
            return []

    def _apply_fill(self, f: Fill, po: PlannedOrder) -> float:
        if f.side == "BUY":
            self.book.apply_fill(f, po.sleeve, self.m.execution.settlement_days,
                                 entry_meta=po.entry_meta or {}, counts_as_new=po.counts_as_new)
            self.journal.record("fill", _fill_payload(f, po.sleeve, po.reason))
            return 0.0
        return self._apply_sell(f, po.sleeve, reason=po.reason)

    def _apply_sell(self, f: Fill, sleeve: str, reason: str) -> float:
        pos = self.book.positions.get(f.symbol)
        old_tag = pos.stop_order_tag if pos else ""
        realized = self.book.apply_fill(f, sleeve, self.m.execution.settlement_days)
        self.journal.record("fill", {**_fill_payload(f, sleeve, reason), "realized": realized})
        if f.symbol not in self.book.positions and old_tag:
            self._cancel_stop_by_tag(old_tag)                    # position gone: no orphan GTC stop
        return realized

    def _release_stop(self, symbol: str) -> None:
        """Cancel the resting GTC stop before an engine SELL so the shares are not reserved
        twice (and a double fill cannot short the account)."""
        pos = self.book.positions.get(symbol)
        if pos and pos.stop_order_tag:
            self._cancel_stop_by_tag(pos.stop_order_tag)
            pos.stop_order_tag = ""

    def _restore_stop(self, symbol: str, report: ExecutionReport) -> None:
        """Re-arm the protective stop for whatever quantity remains after a partial sell."""
        pos = self.book.positions.get(symbol)
        if pos and pos.stop_price and pos.qty > 0:
            self._sync_stop(StopInstruction(symbol, pos.stop_price, pos.qty, replaces_tag="",
                                            reason="re-arm stop after sell"),
                            report, already_tightened=True)

    def _sync_stop(self, instr: StopInstruction, report: ExecutionReport,
                   already_tightened: bool = False) -> None:
        """Place/replace the GTC protective stop at the broker (server-side, survives outages)."""
        pos = self.book.positions.get(instr.symbol)
        if pos is None or instr.stop_price <= 0:
            return
        if not already_tightened and not self.book.tighten_stop(instr.symbol, instr.stop_price):
            if pos.stop_price is None or instr.stop_price > pos.stop_price:
                return                                            # nothing to do / refused
        if instr.replaces_tag:
            self._cancel_stop_by_tag(instr.replaces_tag)
        stop_price = pos.stop_price if pos.stop_price else instr.stop_price
        self._stop_seq += 1
        tag = f"s{self.now():%Y%m%d%H%M%S}-{instr.symbol}-STP{self._stop_seq}"
        s = self.m.risk.stops
        limit = round(stop_price * (1 - s.stop_limit_offset_pct), 2) if s.stop_type == "STP LMT" else None
        req = OrderRequest(client_tag=tag, symbol=instr.symbol, side="SELL", qty=pos.qty,
                           order_type=s.stop_type, stop_price=round(stop_price, 2),
                           limit_price=limit, tif="GTC", contract=self._contract(instr.symbol))
        try:
            status = self.broker.place(req)
        except Exception as exc:
            report.errors.append(f"{instr.symbol}: stop placement failed: {exc}")
            self.alerter.critical(f"stop placement FAILED {instr.symbol}", str(exc))
            return
        if status.state == "rejected":
            report.errors.append(f"{instr.symbol}: stop rejected: {status.reason}")
            self.alerter.critical(f"stop REJECTED {instr.symbol}", status.reason)
            return
        pos.stop_order_tag = tag
        (report.stops_replaced if instr.replaces_tag else report.stops_placed).append(tag)
        self.journal.record("stop_synced", {"symbol": instr.symbol, "stop": stop_price,
                                            "qty": pos.qty, "tag": tag, "reason": instr.reason})

    def _cancel_stop_by_tag(self, tag: str) -> None:
        try:
            for o in self.broker.open_orders():
                if o.client_tag == tag:
                    self.broker.cancel(o.broker_order_id)
        except Exception as exc:
            self.journal.record("error", {"where": "cancel_stop", "tag": tag, "err": str(exc)})

    def _check_slippage(self, req: OrderRequest, avg_price: Optional[float]) -> None:
        if not avg_price or not req.limit_price:
            return
        ref = req.limit_price
        bps = abs(avg_price - ref) / ref * 10_000
        if bps >= self.m.execution.slippage_alert_bps:
            self.alerter.warning(f"slippage {req.symbol}",
                                 f"{req.side} fill {avg_price} vs limit {ref} ({bps:.0f} bps)")


def _fill_payload(f: Fill, sleeve: str, reason: str) -> dict:
    return {"tag": f.client_tag, "symbol": f.symbol, "side": f.side, "qty": f.qty,
            "price": f.price, "commission": f.commission, "sleeve": sleeve, "reason": reason,
            "ts": f.ts.isoformat()}
