"""Engine-owned book: the single source of truth for what the POT holds.

The pot is a slice of the IBKR account. IBKR knows the account; only the book knows which
shares and which cash belong to the agent, at which stop, in which sleeve, since when.
Persisted as versioned JSON (atomic replace); reconciled against the broker every fast loop.
A reconcile mismatch FREEZES new orders — it is never auto-corrected.

Accounting (avg-cost):
  pot_cash            = contributions - buys - fees + sell proceeds
  settled_pot_cash    = pot_cash - not-yet-settled sell proceeds (T+1 trading days)
  pot equity          = pot_cash + market value of book positions
Realized P&L on a SELL = (price - avg_cost) * qty - commission. BUY commissions are
capitalised into avg_cost (same convention as SimBroker / IBKR).

The book only mutates through capital events, fills, stop updates and roll-overs — all of
them journaled by the caller. Nothing in here talks to the network.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from ibagent.broker.base import Fill, Position
from ibagent.common import Sleeve
from ibagent.marketclock import add_trading_days, utc

BOOK_VERSION = 1
QTY_TOL = 1e-6


class BookError(RuntimeError):
    """Corrupt book file or an operation that would corrupt the book."""


def _iso(d: date) -> str:
    return d.isoformat()


def _monday(d: date) -> date:
    from datetime import timedelta
    return d - timedelta(days=d.weekday())


@dataclass
class BookPosition:
    """One engine-owned position. `sleeve` is fixed at entry; a symbol appears at most once."""
    symbol: str
    sleeve: Sleeve
    qty: float
    avg_cost: float
    entry_date: str                       # ISO date of first fill
    entry_price: float                    # first-fill price (R-multiple basis)
    initial_stop: Optional[float] = None  # stop at entry; never replaced
    stop_price: Optional[float] = None    # current stop; only ever tightened
    target_price: Optional[float] = None
    thesis: str = ""
    invalidation: str = ""
    horizon_days: int = 0
    time_stop_date: Optional[str] = None  # spec: ISO date after which the position is force-exited
    partial_taken: bool = False           # trend: +2R partial already sold
    stop_order_tag: str = ""              # client_tag of the GTC stop resting at the broker
    high_price: float = 0.0               # highest mark since entry (trailing basis)
    realized_to_date: float = 0.0         # realized P&L booked by partial sells of THIS position
    peak_qty: float = 0.0                 # largest qty ever held (R-multiple denominator)

    @property
    def initial_risk_per_share(self) -> Optional[float]:
        if self.initial_stop is None:
            return None
        return max(0.0, self.entry_price - self.initial_stop)

    def r_multiple(self, price: float) -> Optional[float]:
        r = self.initial_risk_per_share
        if not r:
            return None
        return (price - self.entry_price) / r


@dataclass
class EquitySnapshot:
    ts: str
    pot_cash: float
    settled_pot_cash: float
    positions_value: float
    equity: float
    sleeve_value: Dict[str, float]        # market value per sleeve (cash excluded)
    sleeve_equity: Dict[str, float]       # core/trend/spec value; 'cash' = pot_cash


@dataclass
class ReconcileMismatch:
    symbol: str
    book_qty: float
    broker_qty: float
    kind: Literal["missing", "short", "extra"]


class Book:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.positions: Dict[str, BookPosition] = {}
        self.pot_cash: float = 0.0
        self.pending_settlements: List[Tuple[str, float]] = []   # (ISO settle date, amount)
        self.pending_withdrawal_usd: float = 0.0
        self.net_contributions: float = 0.0
        self.realized_pnl: Dict[str, float] = {"core": 0.0, "trend": 0.0, "spec": 0.0}
        self.spec_profit_since_sweep: float = 0.0
        self.hwm: Dict[str, float] = {"total": 0.0, "core": 0.0, "trend": 0.0, "spec": 0.0}
        self.day_date: str = ""
        self.day_start_equity: float = 0.0
        self.week_start: str = ""
        self.week_new_positions: int = 0
        self.week_turnover_usd: float = 0.0
        self.cooldowns: Dict[str, str] = {}                      # symbol -> ISO date (inclusive) until blocked
        self.consecutive_spec_losers: int = 0
        self.consecutive_active_losers: int = 0                  # losing full closes, any active sleeve
        self.week_start_equity: float = 0.0                      # equity anchor at the week roll
        self.month_key: str = ""                                 # YYYY-MM the month anchor belongs to
        self.month_start_equity: float = 0.0
        self.entries_paused_until: str = ""                      # ISO date (inclusive); "" = not paused
        self.entries_paused_reason: str = ""
        self.stopout_history: Dict[str, List[str]] = {}          # symbol -> ISO dates of stop-outs
        self.trade_history: Dict[str, List[dict]] = {}           # symbol -> last closed trades {date, realized, r}
        self.frozen: bool = False
        self.frozen_reason: str = ""
        self.halted: bool = False
        self.halted_reason: str = ""
        self.paused_sleeves: Dict[str, str] = {}                 # sleeve -> ISO date until paused
        self.last_fill_ts: str = ""

    # ------------------------------------------------------------------ persistence
    @classmethod
    def load(cls, path: Path | str) -> "Book":
        p = Path(path)
        book = cls(p)
        if not p.exists():
            return book
        try:
            with p.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise BookError(f"book file unreadable: {exc}") from exc
        if data.get("version") != BOOK_VERSION:
            raise BookError(f"book version {data.get('version')} != {BOOK_VERSION}")
        try:
            for k, v in data["positions"].items():
                book.positions[k] = BookPosition(**v)
            for name in ("pot_cash", "pending_withdrawal_usd", "net_contributions", "spec_profit_since_sweep",
                         "day_date", "day_start_equity", "week_start", "week_new_positions", "week_turnover_usd",
                         "consecutive_spec_losers", "consecutive_active_losers", "week_start_equity",
                         "month_key", "month_start_equity", "entries_paused_until", "entries_paused_reason",
                         "frozen", "frozen_reason", "halted", "halted_reason", "last_fill_ts"):
                if name in data:                                 # new fields default on older files
                    setattr(book, name, data[name])
            book.pending_settlements = [tuple(x) for x in data["pending_settlements"]]
            book.realized_pnl = dict(data["realized_pnl"])
            book.hwm = dict(data["hwm"])
            book.cooldowns = dict(data["cooldowns"])
            book.paused_sleeves = dict(data["paused_sleeves"])
            book.stopout_history = {k: list(v) for k, v in data.get("stopout_history", {}).items()}
            book.trade_history = {k: list(v) for k, v in data.get("trade_history", {}).items()}
        except (KeyError, TypeError) as exc:
            raise BookError(f"book file malformed: {exc}") from exc
        return book

    def save(self) -> None:
        data = {
            "version": BOOK_VERSION,
            "positions": {k: asdict(v) for k, v in sorted(self.positions.items())},
            "pot_cash": round(self.pot_cash, 6),
            "pending_settlements": self.pending_settlements,
            "pending_withdrawal_usd": self.pending_withdrawal_usd,
            "net_contributions": self.net_contributions,
            "realized_pnl": self.realized_pnl,
            "spec_profit_since_sweep": self.spec_profit_since_sweep,
            "hwm": self.hwm,
            "day_date": self.day_date,
            "day_start_equity": self.day_start_equity,
            "week_start": self.week_start,
            "week_new_positions": self.week_new_positions,
            "week_turnover_usd": self.week_turnover_usd,
            "cooldowns": self.cooldowns,
            "consecutive_spec_losers": self.consecutive_spec_losers,
            "consecutive_active_losers": self.consecutive_active_losers,
            "week_start_equity": self.week_start_equity,
            "month_key": self.month_key,
            "month_start_equity": self.month_start_equity,
            "entries_paused_until": self.entries_paused_until,
            "entries_paused_reason": self.entries_paused_reason,
            "stopout_history": self.stopout_history,
            "trade_history": self.trade_history,
            "frozen": self.frozen,
            "frozen_reason": self.frozen_reason,
            "halted": self.halted,
            "halted_reason": self.halted_reason,
            "paused_sleeves": self.paused_sleeves,
            "last_fill_ts": self.last_fill_ts,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=self.path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=1)
                fh.flush()
                os.fsync(fh.fileno())
            try:
                os.replace(tmp, self.path)
            except PermissionError:
                # Windows: a sync/AV process (e.g. OneDrive) can hold the target briefly.
                # One short retry; if it still fails, the caller's error path handles it.
                time.sleep(0.5)
                os.replace(tmp, self.path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------ capital
    def apply_contribution(self, amount_usd: float) -> None:
        """Seed or add: cash enters the pot, settled immediately (it is your own cash)."""
        if amount_usd <= 0:
            raise BookError("contribution must be positive")
        self.pot_cash += amount_usd
        self.net_contributions += amount_usd

    def request_withdrawal(self, amount_usd: float) -> None:
        if amount_usd <= 0:
            raise BookError("withdrawal must be positive")
        self.pending_withdrawal_usd += amount_usd

    def payout_withdrawal(self, amount_usd: float, today: date) -> None:
        """Engine transfers settled pot cash out; reduces both cash and the pending marker."""
        if amount_usd <= 0 or amount_usd > self.pending_withdrawal_usd + 1e-9:
            raise BookError("payout exceeds pending withdrawal")
        if amount_usd > self.settled_pot_cash(today) + 1e-9:
            raise BookError("payout exceeds settled pot cash")
        self.pot_cash -= amount_usd
        self.net_contributions -= amount_usd
        self.pending_withdrawal_usd = round(self.pending_withdrawal_usd - amount_usd, 2)

    def settled_pot_cash(self, today: date) -> float:
        unsettled = sum(a for d, a in self.pending_settlements if date.fromisoformat(d) > today)
        return self.pot_cash - unsettled

    def deployable_cash(self, today: date) -> float:
        """Cash new BUYs may spend: settled pot cash minus anything owed to the human."""
        return max(0.0, self.settled_pot_cash(today) - self.pending_withdrawal_usd)

    # ------------------------------------------------------------------ fills
    def apply_fill(self, fill: Fill, sleeve: Sleeve, settlement_days: int = 1, *,
                   entry_meta: Optional[dict] = None, counts_as_new: bool = False) -> float:
        """Apply one fill to the book. Returns realized P&L (0 for BUYs).

        `entry_meta` (first BUY of a position) carries stop/target/thesis fields from the
        validated intent. `counts_as_new` increments the weekly new-position counter.
        """
        ts = utc(fill.ts)
        notional = fill.qty * fill.price
        self.week_turnover_usd += notional
        realized = 0.0
        pos = self.positions.get(fill.symbol)

        if fill.side == "BUY":
            if pos is None:
                meta = entry_meta or {}
                pos = BookPosition(
                    symbol=fill.symbol, sleeve=sleeve, qty=0.0, avg_cost=0.0,
                    entry_date=_iso(ts.date()), entry_price=fill.price,
                    initial_stop=meta.get("stop_price"), stop_price=meta.get("stop_price"),
                    target_price=meta.get("target_price"), thesis=meta.get("thesis", ""),
                    invalidation=meta.get("invalidation", ""), horizon_days=meta.get("horizon_days", 0),
                    stop_order_tag=meta.get("stop_order_tag", ""), high_price=fill.price,
                )
                if sleeve == "spec" and meta.get("time_stop_trading_days"):
                    pos.time_stop_date = _iso(add_trading_days(ts.date(), int(meta["time_stop_trading_days"])))
                self.positions[fill.symbol] = pos
            elif pos.sleeve != sleeve:
                raise BookError(f"{fill.symbol}: fill sleeve {sleeve} != book sleeve {pos.sleeve}")
            new_qty = pos.qty + fill.qty
            pos.avg_cost = (pos.qty * pos.avg_cost + notional + fill.commission) / new_qty
            pos.qty = round(new_qty, 8)
            pos.peak_qty = max(pos.peak_qty, pos.qty)
            self.pot_cash -= notional + fill.commission
            if counts_as_new:
                self.week_new_positions += 1
        else:
            if pos is None or pos.qty + QTY_TOL < fill.qty:
                raise BookError(f"SELL {fill.qty} {fill.symbol} exceeds book qty "
                                f"{pos.qty if pos else 0.0} (book/broker out of sync)")
            if pos.sleeve != sleeve:
                raise BookError(f"{fill.symbol}: fill sleeve {sleeve} != book sleeve {pos.sleeve}")
            realized = round((fill.price - pos.avg_cost) * fill.qty - fill.commission, 2)
            self.realized_pnl[sleeve] = round(self.realized_pnl[sleeve] + realized, 2)
            pos.realized_to_date = round(pos.realized_to_date + realized, 2)
            proceeds = notional - fill.commission
            self.pot_cash += proceeds
            self.pending_settlements.append((_iso(add_trading_days(ts.date(), settlement_days)), proceeds))
            pos.qty = round(pos.qty - fill.qty, 8)
            if pos.qty <= QTY_TOL:
                del self.positions[fill.symbol]
                total = pos.realized_to_date
                if sleeve != "core":
                    irps = pos.initial_risk_per_share
                    r = round(total / (irps * pos.peak_qty), 3) if irps and pos.peak_qty else None
                    hist = self.trade_history.setdefault(fill.symbol, [])
                    hist.append({"date": _iso(ts.date()), "realized": total, "r": r})
                    del hist[:-8]
                    self.consecutive_active_losers = 0 if total > 0 else self.consecutive_active_losers + 1
                if sleeve == "spec":
                    self.spec_profit_since_sweep = round(self.spec_profit_since_sweep + total, 2)
                    self.consecutive_spec_losers = 0 if total > 0 else self.consecutive_spec_losers + 1
        self.last_fill_ts = ts.isoformat()
        return realized

    def settle_through(self, today: date) -> None:
        """Drop settlement markers that have matured (their cash is already in pot_cash)."""
        self.pending_settlements = [(d, a) for d, a in self.pending_settlements
                                    if date.fromisoformat(d) > today]

    # ------------------------------------------------------------------ stops / cooldowns
    def tighten_stop(self, symbol: str, new_stop: float) -> bool:
        """Apply a stop update ONLY if it is tighter (higher, long-only). Returns applied?"""
        pos = self.positions.get(symbol)
        if pos is None or new_stop <= 0:
            return False
        if pos.stop_price is not None and new_stop <= pos.stop_price:
            return False
        pos.stop_price = new_stop
        if pos.initial_stop is None:
            pos.initial_stop = new_stop
        return True

    def add_cooldown(self, symbol: str, today: date, cooldown_days: int) -> None:
        """Per-symbol entry lock; overlapping locks keep the LATEST release date.
        0 days = no lock (day-trader variants re-enter the same session)."""
        if cooldown_days <= 0:
            return
        until = _iso(add_trading_days(today, cooldown_days))
        cur = self.cooldowns.get(symbol, "")
        if until > cur:
            self.cooldowns[symbol] = until

    def record_stop_out(self, symbol: str, today: date, cooldown_days: int) -> None:
        self.add_cooldown(symbol, today, cooldown_days)
        hist = self.stopout_history.setdefault(symbol, [])
        hist.append(_iso(today))
        del hist[:-10]

    def stopouts_within(self, symbol: str, today: date, window_sessions: int) -> int:
        from ibagent.marketclock import trading_days_between
        count = 0
        for d in self.stopout_history.get(symbol, []):
            when = date.fromisoformat(d)
            if when <= today and trading_days_between(when, today) <= window_sessions:
                count += 1
        return count

    def recent_r_sum(self, symbol: str, lookback: int) -> Optional[float]:
        """Cumulative R over the last `lookback` closed trades; None until that many exist
        (or when any of them has no measurable R — fail toward not judging, the trades still
        count via the account-level streaks)."""
        hist = self.trade_history.get(symbol, [])
        if len(hist) < lookback:
            return None
        rs = [t.get("r") for t in hist[-lookback:]]
        if any(r is None for r in rs):
            return None
        return round(sum(rs), 3)

    def in_cooldown(self, symbol: str, today: date) -> bool:
        until = self.cooldowns.get(symbol)
        return until is not None and today <= date.fromisoformat(until)

    def prune_cooldowns(self, today: date) -> None:
        self.cooldowns = {s: d for s, d in self.cooldowns.items() if today <= date.fromisoformat(d)}

    # ------------------------------------------------------------------ valuation / breakers
    def equity(self, prices: Dict[str, float], now: Optional[datetime] = None) -> EquitySnapshot:
        """Mark the book. Raises BookError if any held symbol lacks a price — fail closed,
        never value a position at zero or a stale guess silently."""
        missing = sorted(s for s in self.positions if s not in prices or not prices[s] or prices[s] <= 0)
        if missing:
            raise BookError(f"no price for held symbols: {missing}")
        sleeve_value = {"core": 0.0, "trend": 0.0, "spec": 0.0}
        for pos in self.positions.values():
            sleeve_value[pos.sleeve] += pos.qty * prices[pos.symbol]
        total_value = sum(sleeve_value.values())
        ts = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        today = ts.date()
        return EquitySnapshot(
            ts=ts.isoformat(timespec="seconds"),
            pot_cash=round(self.pot_cash, 2),
            settled_pot_cash=round(self.settled_pot_cash(today), 2),
            positions_value=round(total_value, 2),
            equity=round(self.pot_cash + total_value, 2),
            sleeve_value={k: round(v, 2) for k, v in sleeve_value.items()},
            sleeve_equity={**{k: round(v, 2) for k, v in sleeve_value.items()},
                           "cash": round(self.pot_cash, 2)},
        )

    def update_hwm(self, snap: EquitySnapshot) -> None:
        self.hwm["total"] = max(self.hwm["total"], snap.equity)
        for s in ("core", "trend", "spec"):
            self.hwm[s] = max(self.hwm[s], snap.sleeve_value[s])

    def drawdown(self, snap: EquitySnapshot, scope: str = "total") -> float:
        """Fractional drawdown from HWM (0 = at high). scope: total|core|trend|spec."""
        peak = self.hwm.get(scope, 0.0)
        if peak <= 0:
            return 0.0
        cur = snap.equity if scope == "total" else snap.sleeve_value[scope]
        return max(0.0, (peak - cur) / peak)

    def update_high_prices(self, prices: Dict[str, float]) -> None:
        for pos in self.positions.values():
            p = prices.get(pos.symbol)
            if p and p > pos.high_price:
                pos.high_price = p

    # ------------------------------------------------------------------ roll-overs
    def ensure_day(self, today: date, current_equity: float) -> bool:
        """Reset the daily loss anchor on a new day. Returns True if the day rolled."""
        iso = _iso(today)
        if self.day_date == iso:
            return False
        self.day_date, self.day_start_equity = iso, current_equity
        return True

    def ensure_week(self, today: date, current_equity: float = 0.0) -> bool:
        """Reset weekly counters (and the drawdown anchor) on a new ISO week."""
        wk = _iso(_monday(today))
        if self.week_start == wk:
            if self.week_start_equity <= 0 < current_equity:
                self.week_start_equity = current_equity        # first mark of an already-rolled week
            return False
        self.week_start, self.week_new_positions, self.week_turnover_usd = wk, 0, 0.0
        self.week_start_equity = current_equity
        return True

    def ensure_month(self, today: date, current_equity: float = 0.0) -> bool:
        key = today.strftime("%Y-%m")
        if self.month_key == key:
            if self.month_start_equity <= 0 < current_equity:
                self.month_start_equity = current_equity
            return False
        self.month_key, self.month_start_equity = key, current_equity
        return True

    def daily_loss_pct(self, current_equity: float) -> float:
        if self.day_start_equity <= 0:
            return 0.0
        return max(0.0, (self.day_start_equity - current_equity) / self.day_start_equity)

    def weekly_loss_pct(self, current_equity: float) -> float:
        if self.week_start_equity <= 0:
            return 0.0
        return max(0.0, (self.week_start_equity - current_equity) / self.week_start_equity)

    def monthly_loss_pct(self, current_equity: float) -> float:
        if self.month_start_equity <= 0:
            return 0.0
        return max(0.0, (self.month_start_equity - current_equity) / self.month_start_equity)

    # ------------------------------------------------------------------ entry pause (all sleeves)
    def pause_entries(self, until: date, reason: str) -> None:
        if _iso(until) > self.entries_paused_until:
            self.entries_paused_until, self.entries_paused_reason = _iso(until), reason[:200]

    def entries_paused(self, today: date) -> bool:
        return bool(self.entries_paused_until) and today <= date.fromisoformat(self.entries_paused_until)

    # ------------------------------------------------------------------ freeze / halt / pause
    def freeze(self, reason: str) -> None:
        self.frozen, self.frozen_reason = True, reason

    def unfreeze(self) -> None:
        self.frozen, self.frozen_reason = False, ""

    def halt(self, reason: str) -> None:
        self.halted, self.halted_reason = True, reason

    def pause_sleeve(self, sleeve: str, until: date) -> None:
        self.paused_sleeves[sleeve] = _iso(until)

    def is_sleeve_paused(self, sleeve: str, today: date) -> bool:
        until = self.paused_sleeves.get(sleeve)
        return until is not None and today <= date.fromisoformat(until)

    def prune_pauses(self, today: date) -> None:
        self.paused_sleeves = {s: d for s, d in self.paused_sleeves.items()
                               if today <= date.fromisoformat(d)}

    # ------------------------------------------------------------------ reconcile
    def reconcile(self, broker_positions: List[Position], *, dedicated: bool,
                  qty_tol: float = 1e-4) -> List[ReconcileMismatch]:
        """Compare the book against IBKR.

        Shared account (dedicated=False): every book position must exist at the broker with
        at least the book's quantity (other holdings in the account are none of our business).
        Dedicated account: quantities must match exactly and the broker may hold nothing the
        book doesn't know about.
        """
        broker = {p.symbol: p.qty for p in broker_positions}
        out: List[ReconcileMismatch] = []
        for sym, pos in sorted(self.positions.items()):
            have = broker.get(sym, 0.0)
            if have + qty_tol < pos.qty:
                kind: Literal["missing", "short"] = "missing" if have <= qty_tol else "short"
                out.append(ReconcileMismatch(symbol=sym, book_qty=pos.qty, broker_qty=have, kind=kind))
            elif dedicated and abs(have - pos.qty) > qty_tol:
                out.append(ReconcileMismatch(symbol=sym, book_qty=pos.qty, broker_qty=have, kind="extra"))
        if dedicated:
            for sym, qty in sorted(broker.items()):
                if abs(qty) > qty_tol and sym not in self.positions:
                    out.append(ReconcileMismatch(symbol=sym, book_qty=0.0, broker_qty=qty, kind="extra"))
        return out
