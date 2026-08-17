"""Risk layer: the ONLY path from a model Decision to orders.

plan_orders() is a pure function over (mandate, book, quotes, atrs, decision, now).
It never talks to the network and never mutates the book — the supervisor applies fills.

Enforcement order (everything the model asked for is untrusted):
  0. halted / frozen / kill / outside trade window        -> HOLD (nothing planned)
  1. structural sanity is schemas.py's job; here: whitelist, sleeve membership, sleeve pause,
     cooldown, operating floor, no averaging down
  2. weights: per-position cap (position_cap_usd), active cap x risk_multiplier (pro-rata scale)
  3. sizing: risk-based qty from stop distance (hard-cap overshoot allowed to reach
     min_position_usd, else skip), open-risk cap
  4. cash/friction: settled pot cash, min order, fee cap, weekly turnover + new-position caps
  5. stops: model stop clamped to mandate distance bounds else engine ATR stop; missing ATR
     -> entry rejected (fail closed). Stop updates: tighter-only.
Exits are privileged: sells that reduce risk bypass entry gates (turnover, caps, pauses).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Literal, Optional, Tuple

from ibagent.book import Book, BookPosition
from ibagent.broker.base import OrderRequest, Quote
from ibagent.common import ActiveSleeve, Side, Sleeve
from ibagent.config import Mandate
from ibagent.fees import estimate_commission
from ibagent.marketclock import in_no_trade_window, utc
from ibagent.schemas import Decision, PositionIntent

QTY_DP = 4                       # fractional share precision
_EPS = 1e-9


@dataclass(frozen=True)
class Rejection:
    symbol: str
    what: str                    # "entry" | "add" | "stop_update" | "decision"
    reason: str


@dataclass(frozen=True)
class PlannedOrder:
    req: OrderRequest
    sleeve: Sleeve
    intent: Literal["exit", "trim", "entry", "add"]
    reason: str = ""
    entry_meta: Optional[dict] = None     # for Book.apply_fill on new entries
    counts_as_new: bool = False


@dataclass(frozen=True)
class StopInstruction:
    """Replace/place the GTC protective stop for a held position (tighten-only, verified)."""
    symbol: str
    stop_price: float
    qty: float
    replaces_tag: str            # existing stop order client_tag ("" = none resting)
    reason: str = ""


@dataclass
class Plan:
    hold: bool = False
    hold_reason: str = ""
    orders: List[PlannedOrder] = field(default_factory=list)      # exits first, then entries
    stop_instructions: List[StopInstruction] = field(default_factory=list)
    rejections: List[Rejection] = field(default_factory=list)
    equity: float = 0.0


def _mark(q: Quote) -> Optional[float]:
    m = q.mid
    return float(m) if m and m > 0 else None


def _limit_price(q: Quote, side: Side, offset_bps: int) -> Optional[float]:
    """Marketable limit: BUY <= ask*(1+off), SELL >= bid*(1-off). Falls back to last +/- off."""
    off = offset_bps / 10_000.0
    if side == "BUY":
        ref = q.ask if (q.ask and q.ask > 0) else q.last
        return round(ref * (1 + off), 2) if ref and ref > 0 else None
    ref = q.bid if (q.bid and q.bid > 0) else q.last
    return round(ref * (1 - off), 2) if ref and ref > 0 else None


def _tag(run_type: str, d: datetime, symbol: str, side: str, suffix: str = "") -> str:
    base = f"{run_type[0]}{d.date().isoformat()}-{symbol}-{side}"
    return f"{base}-{suffix}" if suffix else base


def _resolve_stop(mandate: Mandate, sleeve: ActiveSleeve, price: float,
                  intent_stop: Optional[float], atr: Optional[float]) -> Tuple[Optional[float], str]:
    """Model stop if within mandate distance bounds, else engine ATR stop, else (None, why)."""
    s = mandate.risk.stops
    lo = price * (1 - s.max_distance_pct[sleeve])
    hi = price * (1 - s.min_distance_pct)
    if intent_stop is not None and lo - _EPS <= intent_stop <= hi + _EPS:
        return round(intent_stop, 4), "model stop"
    if s.method == "pct":
        return round(price * (1 - s.pct_distance[sleeve]), 4), "engine pct stop"
    if atr and atr > 0:
        eng = price - s.atr_multiple[sleeve] * atr
        return round(min(max(eng, lo), hi), 4), "engine ATR stop (clamped)"
    return None, "no valid stop: model stop outside mandate bounds and no ATR available"


def open_risk_usd(book: Book, prices: Dict[str, float]) -> float:
    """Sum over active positions of qty x (price - stop). Stopless positions count at the
    mandate's worst case via price (fail conservative: full position value)."""
    total = 0.0
    for pos in book.positions.values():
        if pos.sleeve == "core" or pos.qty <= 0:
            continue
        price = prices.get(pos.symbol, pos.avg_cost)
        risk = price - pos.stop_price if pos.stop_price else price
        total += pos.qty * max(0.0, risk)
    return total


def plan_orders(mandate: Mandate, book: Book, quotes: Dict[str, Quote], atrs: Dict[str, float],
                decision: Decision, now: datetime, *, kill_switch: bool = False) -> Plan:
    now = utc(now)
    today = now.date()
    plan = Plan()

    # ---- 0. global refusals -------------------------------------------------------------
    if kill_switch:
        return Plan(hold=True, hold_reason="kill switch active")
    if book.halted:
        return Plan(hold=True, hold_reason=f"halted: {book.halted_reason}")
    if book.frozen:
        return Plan(hold=True, hold_reason=f"frozen: {book.frozen_reason}")
    if mandate.execution.rth_only and in_no_trade_window(
            now, mandate.execution.no_trade_first_minutes, mandate.execution.no_trade_last_minutes):
        return Plan(hold=True, hold_reason="outside RTH trade window")

    # ---- prices / equity (fail closed on missing marks for held symbols) ----------------
    prices: Dict[str, float] = {}
    for sym, q in quotes.items():
        m = _mark(q)
        if m:
            prices[sym] = m
    try:
        snap = book.equity(prices, now)
    except Exception as exc:
        return Plan(hold=True, hold_reason=f"cannot mark book: {exc}")
    plan.equity = snap.equity
    stale_cutoff = mandate.circuit_breakers.data_stale_seconds
    for pos in book.positions.values():
        q = quotes.get(pos.symbol)
        if q and (now - utc(q.ts)).total_seconds() > stale_cutoff:
            return Plan(hold=True, hold_reason=f"stale quote for held {pos.symbol}", equity=snap.equity)

    offset = mandate.execution.limit_offset_bps
    model = mandate.capital.commission_model

    # ---- stop updates (both actions): tighten-only, verified against the book -----------
    for upd in decision.stop_updates:
        pos = book.positions.get(upd.symbol)
        if pos is None or pos.sleeve == "core":
            plan.rejections.append(Rejection(upd.symbol, "stop_update", "not a held active position"))
            continue
        if pos.stop_price is not None and upd.stop_price <= pos.stop_price + _EPS:
            plan.rejections.append(Rejection(upd.symbol, "stop_update",
                                             f"{upd.stop_price} does not tighten stop {pos.stop_price}"))
            continue
        price = prices.get(upd.symbol)
        if price is not None and upd.stop_price >= price:
            plan.rejections.append(Rejection(upd.symbol, "stop_update", "stop at/above market would fire instantly"))
            continue
        plan.stop_instructions.append(StopInstruction(upd.symbol, round(upd.stop_price, 4), pos.qty,
                                                      replaces_tag=pos.stop_order_tag, reason=upd.reason))

    if decision.action == "no_change":
        return plan

    # ---- 1. sanitize target book --------------------------------------------------------
    kept: List[PositionIntent] = []
    for p in decision.positions:
        held = book.positions.get(p.symbol)
        if not mandate.universe.is_allowed(p.symbol, p.sleeve):
            plan.rejections.append(Rejection(p.symbol, "entry", f"not whitelisted for sleeve {p.sleeve}"))
            continue
        if held is not None and held.sleeve != p.sleeve:
            plan.rejections.append(Rejection(p.symbol, "entry",
                                             f"held in sleeve {held.sleeve}; sleeve migration not allowed"))
            continue
        kept.append(p)

    # active-weight cap x risk_multiplier: scale everything down pro-rata if exceeded
    cap_weight = mandate.active_weight_cap() * decision.risk_multiplier
    total_w = sum(p.target_weight for p in kept)
    scale = min(1.0, cap_weight / total_w) if total_w > cap_weight + _EPS else 1.0

    target_syms = {p.symbol for p in kept}

    # ---- exits first: held active positions not in target, or reduced ------------------
    entries: List[Tuple[PositionIntent, float]] = []      # (intent, desired notional diff)
    for sym, pos in sorted(book.positions.items()):
        if pos.sleeve == "core" or pos.qty <= 0:
            continue
        if sym not in target_syms:
            q = quotes.get(sym)
            lp = _limit_price(q, "SELL", offset) if q else None
            if lp is None:
                plan.rejections.append(Rejection(sym, "exit", "no quote; exit deferred"))
                continue
            plan.orders.append(PlannedOrder(
                req=OrderRequest(client_tag=_tag(decision.run_type, now, sym, "SELL"), symbol=sym,
                                 side="SELL", qty=pos.qty, order_type="LMT", limit_price=lp, tif="DAY"),
                sleeve=pos.sleeve, intent="exit", reason="not in target book"))

    for p in kept:
        price = prices.get(p.symbol)
        if price is None:
            plan.rejections.append(Rejection(p.symbol, "entry", "no usable quote"))
            continue
        held = book.positions.get(p.symbol)
        cur_usd = held.qty * price if held else 0.0
        target_usd = min(p.target_weight * scale * snap.equity,
                         mandate.position_cap_usd(p.sleeve, snap.equity))
        diff = target_usd - cur_usd
        if held and diff < 0:
            trim_usd = -diff
            if trim_usd >= mandate.capital.min_order_usd:
                qty = min(held.qty, round(trim_usd / price, QTY_DP))
                lp = _limit_price(quotes[p.symbol], "SELL", offset)
                if qty > 0 and lp:
                    plan.orders.append(PlannedOrder(
                        req=OrderRequest(client_tag=_tag(decision.run_type, now, p.symbol, "SELL"),
                                         symbol=p.symbol, side="SELL", qty=qty, order_type="LMT",
                                         limit_price=lp, tif="DAY"),
                        sleeve=held.sleeve, intent="trim", reason="target below current"))
        elif diff > 0:
            entries.append((p, diff))

    # ---- entry gates ---------------------------------------------------------------------
    if not mandate.is_operating(snap.equity):
        for p, _ in entries:
            plan.rejections.append(Rejection(p.symbol, "entry",
                                             f"equity {snap.equity:.0f} below operating floor"))
        return plan
    if book.entries_paused(today):
        for p, _ in entries:
            plan.rejections.append(Rejection(p.symbol, "entry",
                                             f"entries paused until {book.entries_paused_until}: "
                                             f"{book.entries_paused_reason}"))
        return plan
    # HALF-RISK band: in a >10% drawdown from the high-water mark, new risk is halved
    risk_scale = 1.0
    hwm = book.hwm.get("total", 0.0)
    if hwm > 0 and (hwm - snap.equity) / hwm >= mandate.circuit_breakers.half_risk_drawdown_pct:
        risk_scale = 0.5

    open_risk = open_risk_usd(book, prices)
    max_risk = mandate.risk.max_total_open_risk_pct * snap.equity
    turnover_budget = mandate.risk.max_turnover_pct_per_week * snap.equity - book.week_turnover_usd \
        - sum(o.req.qty * (o.req.limit_price or 0) for o in plan.orders)
    new_budget = mandate.risk.max_new_positions_per_week - book.week_new_positions
    cash = book.deployable_cash(today)
    # sleeve position counts after planned exits
    exiting = {o.req.symbol for o in plan.orders if o.intent == "exit"}
    count: Dict[str, int] = {"trend": 0, "spec": 0}
    for sym, pos in book.positions.items():
        if pos.sleeve in count and sym not in exiting and pos.qty > 0:
            count[pos.sleeve] += 1

    # deterministic priority: bigger intended notional first (fewer, larger positions)
    entries.sort(key=lambda e: (-e[1], e[0].symbol))

    for p, diff in entries:
        sleeve: ActiveSleeve = p.sleeve
        price = prices[p.symbol]
        held = book.positions.get(p.symbol)
        is_new = held is None
        what = "entry" if is_new else "add"

        if book.is_sleeve_paused(sleeve, today):
            plan.rejections.append(Rejection(p.symbol, what, f"{sleeve} sleeve paused"))
            continue
        if is_new and book.in_cooldown(p.symbol, today):
            plan.rejections.append(Rejection(p.symbol, what, "cooldown after stop-out"))
            continue
        if not is_new and mandate.risk.no_averaging_down and price <= held.avg_cost + _EPS:
            plan.rejections.append(Rejection(p.symbol, what, "no averaging down (price <= avg cost)"))
            continue
        if is_new and new_budget <= 0:
            plan.rejections.append(Rejection(p.symbol, what, "weekly new-position cap reached"))
            continue
        if is_new and count[sleeve] >= mandate.max_positions(sleeve, snap.equity):
            plan.rejections.append(Rejection(p.symbol, what, f"{sleeve} at max positions"))
            continue

        stop, stop_src = _resolve_stop(mandate, sleeve, price, p.stop_price, atrs.get(p.symbol))
        if stop is None:
            plan.rejections.append(Rejection(p.symbol, what, stop_src))
            continue
        if not is_new and held.stop_price is not None and stop < held.stop_price:
            stop = held.stop_price                       # adds never widen the resting stop

        # risk-based size, capped by the requested diff
        risk_usd = mandate.per_trade_risk_usd(sleeve, snap.equity) * risk_scale
        per_share_risk = price - stop
        qty = min(diff / price, risk_usd / per_share_risk)
        notional = qty * price
        floor = mandate.capital.min_position_usd if is_new else mandate.capital.min_order_usd
        if notional < floor:
            hard = mandate.per_trade_risk_usd(sleeve, snap.equity, hard_cap=True) * risk_scale
            qty = min(diff / price, hard / per_share_risk)
            notional = qty * price
            if notional < floor:
                plan.rejections.append(Rejection(
                    p.symbol, what, f"size {notional:.0f} below {floor:.0f} even at hard-cap risk"))
                continue
        if not mandate.broker.fractional_shares:
            # broker/account rejects fractional API orders: whole shares only, fail closed
            qty = float(int(qty))
            notional = qty * price
            if qty < 1:
                plan.rejections.append(Rejection(
                    p.symbol, what, f"needs fractional shares (1 share = {price:.0f} > budget)"))
                continue
            if notional < floor:
                plan.rejections.append(Rejection(
                    p.symbol, what, f"whole-share size {notional:.0f} below {floor:.0f}"))
                continue
        qty = round(qty, QTY_DP)
        notional = qty * price

        risk_added = qty * per_share_risk
        if open_risk + risk_added > max_risk + _EPS:
            plan.rejections.append(Rejection(p.symbol, what,
                                             f"open-risk cap: {open_risk + risk_added:.0f} > {max_risk:.0f}"))
            continue
        if notional > turnover_budget + _EPS:
            plan.rejections.append(Rejection(p.symbol, what, "weekly turnover cap reached"))
            continue
        fee = estimate_commission(model, qty, price, "BUY")
        if 100.0 * fee / notional > mandate.capital.max_fee_pct_per_trade:
            plan.rejections.append(Rejection(p.symbol, what,
                                             f"fee {100 * fee / notional:.2f}% exceeds cap"))
            continue
        lp = _limit_price(quotes[p.symbol], "BUY", offset)
        if lp is None:
            plan.rejections.append(Rejection(p.symbol, what, "no usable quote"))
            continue
        need = qty * lp + fee
        if need > cash + _EPS:
            plan.rejections.append(Rejection(p.symbol, what,
                                             f"settled cash: need {need:.2f}, have {cash:.2f}"))
            continue

        cash -= need
        open_risk += risk_added
        turnover_budget -= notional
        if is_new:
            new_budget -= 1
            count[sleeve] += 1
        stop_tag = _tag(decision.run_type, now, p.symbol, "STP")
        entry_meta = {
            "stop_price": stop, "target_price": p.target_price, "thesis": p.thesis,
            "invalidation": p.invalidation, "horizon_days": p.horizon_days, "stop_order_tag": stop_tag,
            "stop_source": stop_src,
        }
        if sleeve == "spec":
            entry_meta["time_stop_trading_days"] = mandate.risk.targets.spec.time_stop_trading_days
        plan.orders.append(PlannedOrder(
            req=OrderRequest(client_tag=_tag(decision.run_type, now, p.symbol, "BUY"), symbol=p.symbol,
                             side="BUY", qty=qty, order_type="LMT", limit_price=lp, tif="DAY"),
            sleeve=sleeve, intent=what, reason=stop_src, entry_meta=entry_meta, counts_as_new=is_new))
        plan.stop_instructions.append(StopInstruction(
            p.symbol, stop, qty if is_new else round(held.qty + qty, QTY_DP),
            replaces_tag=(held.stop_order_tag if held else ""), reason=f"protective stop ({stop_src})"))

    plan.orders.sort(key=lambda o: (o.req.side != "SELL",))   # exits/trims first, stable
    return plan
