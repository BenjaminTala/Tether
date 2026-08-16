"""Sleeve engine: deterministic housekeeping the model never touches.

Everything here is a pure function over (mandate, book, prices, ...) returning intents;
the supervisor turns intents into orders via the same execution path as decisions.

  protective_actions   trend +2R partial take, ATR trailing stops (tighten-only),
                       spec take-profit and time stops. Runs daily; needs no model.
  evaluate_breakers    circuit-breaker state: total halt, sleeve pauses, daily-loss pause,
                       consecutive-loser pause. Fail closed: unreadable inputs -> halt.
  core_rebalance       core holdings back to band targets + spec-profit sweep.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Literal, Optional, Set

from ibagent.book import Book, EquitySnapshot
from ibagent.common import Side, Sleeve
from ibagent.config import Mandate

ProtectiveKind = Literal["partial_take", "take_profit", "time_stop", "trail_stop"]


@dataclass(frozen=True)
class ProtectiveAction:
    kind: ProtectiveKind
    symbol: str
    sleeve: Sleeve
    sell_qty: float = 0.0            # exits/partials
    new_stop: float = 0.0            # trail_stop only
    reason: str = ""


@dataclass(frozen=True)
class RebalanceIntent:
    symbol: str
    side: Side
    usd: float
    reason: str = ""


@dataclass(frozen=True)
class BreakerState:
    halt: bool = False
    pause_all_entries: bool = False              # daily loss breaker
    paused_sleeves: Set[str] = field(default_factory=set)
    reasons: List[str] = field(default_factory=list)

    @property
    def any_tripped(self) -> bool:
        return self.halt or self.pause_all_entries or bool(self.paused_sleeves)


# --------------------------------------------------------------------------- protective actions

def protective_actions(mandate: Mandate, book: Book, prices: Dict[str, float],
                       atrs: Dict[str, float], today: date) -> List[ProtectiveAction]:
    """Daily deterministic trade management for held trend/spec positions.

    A held symbol with no price or (for trailing) no ATR yields NO action — the GTC stop at
    the broker remains the protection; we never manage a position off data we don't have.
    """
    out: List[ProtectiveAction] = []
    t = mandate.risk.targets
    for pos in sorted(book.positions.values(), key=lambda p: p.symbol):
        if pos.sleeve == "core" or pos.qty <= 0:
            continue
        price = prices.get(pos.symbol)
        if not price or price <= 0:
            continue
        if pos.sleeve == "spec":
            if price >= pos.entry_price * (1.0 + t.spec.take_profit_pct):
                out.append(ProtectiveAction("take_profit", pos.symbol, "spec", sell_qty=pos.qty,
                                            reason=f"+{t.spec.take_profit_pct:.0%} target hit"))
                continue
            if pos.time_stop_date and today >= date.fromisoformat(pos.time_stop_date):
                out.append(ProtectiveAction("time_stop", pos.symbol, "spec", sell_qty=pos.qty,
                                            reason=f"time stop {pos.time_stop_date} reached"))
                continue
        else:  # trend
            r = pos.r_multiple(price)
            if not pos.partial_taken and r is not None and r >= t.trend.partial_take_r:
                qty = round(pos.qty * t.trend.partial_fraction, 4)
                if qty > 0:
                    out.append(ProtectiveAction("partial_take", pos.symbol, "trend", sell_qty=qty,
                                                reason=f"+{r:.1f}R >= {t.trend.partial_take_r}R partial"))
            atr = atrs.get(pos.symbol)
            if atr and atr > 0:
                trail = round(pos.high_price - t.trend.trail_atr_multiple * atr, 4)
                if trail > 0 and (pos.stop_price is None or trail > pos.stop_price) and trail < price:
                    out.append(ProtectiveAction("trail_stop", pos.symbol, "trend", new_stop=trail,
                                                reason=f"trail {t.trend.trail_atr_multiple}xATR below high "
                                                       f"{pos.high_price:.2f}"))
    return out


# --------------------------------------------------------------------------- circuit breakers

def evaluate_breakers(mandate: Mandate, book: Book, snap: EquitySnapshot) -> BreakerState:
    """Pure read of breaker conditions. The supervisor persists the consequences
    (book.halt / book.pause_sleeve) and alerts; risk.plan_orders refuses accordingly."""
    cb = mandate.circuit_breakers
    reasons: List[str] = []
    halt = book.halted
    if halt:
        reasons.append(f"halted: {book.halted_reason}")
    dd_total = book.drawdown(snap, "total")
    if dd_total >= cb.total_drawdown_halt_pct:
        halt = True
        reasons.append(f"total drawdown {dd_total:.1%} >= {cb.total_drawdown_halt_pct:.0%} (halt)")
    paused: Set[str] = set()
    today = date.fromisoformat(snap.ts[:10])
    for sleeve in ("trend", "spec"):
        if book.is_sleeve_paused(sleeve, today):
            paused.add(sleeve)
            reasons.append(f"{sleeve} paused until {book.paused_sleeves[sleeve]}")
            continue
        dd = book.drawdown(snap, sleeve)
        if dd >= cb.sleeve_drawdown_pause_pct:
            paused.add(sleeve)
            reasons.append(f"{sleeve} drawdown {dd:.1%} >= {cb.sleeve_drawdown_pause_pct:.0%} (pause)")
    if book.consecutive_spec_losers >= cb.consecutive_losers_pause:
        paused.add("spec")
        reasons.append(f"{book.consecutive_spec_losers} consecutive spec losers (pause)")
    daily = book.daily_loss_pct(snap.equity)
    pause_all = daily >= cb.daily_loss_pause_pct
    if pause_all:
        reasons.append(f"daily loss {daily:.1%} >= {cb.daily_loss_pause_pct:.0%} (no new entries)")
    return BreakerState(halt=halt, pause_all_entries=pause_all, paused_sleeves=paused, reasons=reasons)


def sleeve_pause_until(today: date, days: int = 30) -> date:
    return today + timedelta(days=days)


# --------------------------------------------------------------------------- core rebalance

def core_rebalance(mandate: Mandate, book: Book, snap: EquitySnapshot,
                   prices: Dict[str, float], today: date) -> tuple[List[RebalanceIntent], float]:
    """Core holdings back to target bands, plus the spec-profit sweep.

    Returns (intents, sweep_usd). sweep_usd > 0 means the caller must reset
    book.spec_profit_since_sweep after the sweep buys are journaled — the sweep buys core
    holdings with realized spec profit even when core is inside its band.
    """
    core_cfg = mandate.sleeves.core
    profile = mandate.universe.active
    sweep_usd = 0.0
    if book.spec_profit_since_sweep > 0:
        sweep_usd = round(book.spec_profit_since_sweep * mandate.sleeves.spec_profit_sweep_to_core, 2)
    core_target_total = snap.equity * core_cfg.weight
    intents: List[RebalanceIntent] = []
    cash_left = book.deployable_cash(today)
    for symbol, weight in sorted(profile.core_holdings.items()):
        price = prices.get(symbol)
        if not price or price <= 0:
            continue                                        # fail closed per holding
        pos = book.positions.get(symbol)
        cur_usd = (pos.qty * price) if pos else 0.0
        target_usd = core_target_total * weight + sweep_usd * weight
        diff = target_usd - cur_usd
        threshold = max(mandate.capital.min_order_usd, core_cfg.band * max(target_usd, 1.0))
        in_band = abs(diff) <= threshold
        sweep_part = sweep_usd * weight
        if in_band and sweep_part < mandate.capital.min_order_usd:
            continue
        if in_band:                                         # only the sweep buy remains
            diff = sweep_part
        if diff > 0:
            amount = round(min(diff, cash_left), 2)
            if amount >= mandate.capital.min_order_usd:
                cash_left -= amount
                intents.append(RebalanceIntent(symbol, "BUY", amount,
                                               reason="core rebalance" + (" + sweep" if sweep_usd else "")))
        else:
            amount = round(min(-diff, cur_usd), 2)
            if amount >= mandate.capital.min_order_usd:
                intents.append(RebalanceIntent(symbol, "SELL", amount, reason="core rebalance"))
    return intents, sweep_usd
