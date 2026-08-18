"""Supervisor: the single long-running process that owns everything.

One writer to the book, one broker connection, one scheduler. Each tick (fast loop during
RTH, slow loop otherwise) is a full pass:

  heartbeat -> kill switch -> broker connection -> external fill sync (stop-outs)
  -> mark book / HWMs / day-week rolls -> reconcile (mismatch = freeze)
  -> circuit breakers (halt = liquidate active sleeves, human restart required)
  -> due jobs: news poll + event gate, protective actions, daily check, weekly review,
     daily report, monthly core rebalance

Degradation is graceful by construction: every Claude failure becomes HOLD inside the
orchestrator, protective stops live at the broker as GTC orders, and any unexpected
exception in a tick is journaled and alerted, never fatal. Ctrl+C / SIGTERM exits cleanly.
"""
from __future__ import annotations

import json
import signal
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

from ibagent.agent.orchestrator import LLMState, run_cycle
from ibagent.alerts import Alerter, build_alerter, get_secret
from ibagent.book import Book
from ibagent.capital import CapitalLedger
from ibagent.broker.base import Bar, Broker, Contract, Quote
from ibagent.config import Mandate
from ibagent.data import SymbolStats, atr as calc_atr, stats_table
from ibagent.execution import Executor
from ibagent.journal import Journal
from ibagent.llm.runner import ClaudeCodeRunner, LLMRunner
from ibagent.marketclock import is_rth, is_trading_day, previous_trading_day, utc
from ibagent.news.ingest import DEFAULT_FEEDS, NewsStore, poll as news_poll
from ibagent.news.scoring import (EventGateState, build_digest, check_event_gate, score_items)
from ibagent.schemas import decision_json_schema_text
from ibagent.telegram_in import HELP_TEXT, classify, poll as tg_poll
from ibagent.sleeves import core_rebalance, evaluate_breakers, protective_actions, sleeve_pause_until

DATA_DIR = Path("data")
BARS_FOR_STATS = 300
PROTECTIVE_MIN_SPACING_S = 900
STATUS_UPDATE_SPACING_S = 7200          # intraday Telegram status every 2h during RTH


@dataclass
class ScheduleState:
    last_weekly: str = ""                # ISO date of the week's Monday
    last_daily: str = ""                 # ISO date
    last_report: str = ""
    last_rebalance_period: str = ""      # YYYY-MM (monthly) or ISO Monday (weekly)
    last_news_poll_ts: float = 0.0
    last_protective_ts: float = 0.0
    last_status_ts: float = 0.0
    telegram_offset: int = 0
    last_fill_sync: str = ""             # ISO datetime
    watchlist: List[str] = field(default_factory=list)
    event_gate: dict = field(default_factory=dict)
    kill_handled: bool = False

    @classmethod
    def load(cls, path: Path) -> "ScheduleState":
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            s = cls()
            for k in s.__dict__:
                if k in d:
                    setattr(s, k, d[k])
            return s
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.__dict__), encoding="utf-8")
        tmp.replace(path)


def _monday(d: date) -> str:
    return (d - timedelta(days=d.weekday())).isoformat()


class Supervisor:
    def __init__(self, mandate: Mandate, broker: Broker, runner: Optional[LLMRunner] = None,
                 data_dir: Path = DATA_DIR, alerter: Optional[Alerter] = None,
                 now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 sleeper: Callable[[float], None] = time.sleep,
                 feeds: Optional[Sequence[str]] = None, skills_dir: Optional[Path] = None):
        self.m = mandate
        self.broker = broker
        self.now_fn = now_fn
        self.sleep = sleeper
        self.data_dir = Path(data_dir)
        self.tz = ZoneInfo(mandate.cadence.market_timezone)
        self.journal = Journal(mandate.journal.dir)
        self.alerter = alerter or build_alerter(mandate.alerts)
        self.book = Book.load(self.data_dir / "book.json")
        self.executor = Executor(mandate, broker, self.book, self.journal, self.alerter,
                                 sleeper=sleeper, now_fn=now_fn)
        self.runner: LLMRunner = runner or ClaudeCodeRunner(mandate.llm, decision_json_schema_text())
        self.state = ScheduleState.load(self.data_dir / "schedule_state.json")
        self.news = NewsStore(self.data_dir / "news_state.json")
        self.feeds = list(feeds) if feeds is not None else DEFAULT_FEEDS
        self.skills_dir = skills_dir if skills_dir is not None else Path("skills")
        self.llm_state_path = self.data_dir / "llm_state.json"
        self.heartbeat_path = self.data_dir / "heartbeat.txt"
        self._stop = False
        self._scored_recent: list = []
        self._bars_cache: Dict[str, List[Bar]] = {}
        self._bars_cache_day: str = ""
        self.sync_capital()

    def sync_capital(self) -> None:
        """Carry human ledger events (seed/add/withdraw) into the book. Idempotent: called at
        startup and every tick, so `ibagent capital add` takes effect without a restart."""
        ledger = CapitalLedger(self.data_dir / "capital_events.jsonl")
        target = ledger.net_contributions()
        current = self.book.net_contributions
        after_pending = current - self.book.pending_withdrawal_usd
        changed = False
        if target > current + 0.005:
            amount = round(target - current, 2)
            self.book.apply_contribution(amount)
            # A deposit is not profit: shift the P&L anchors so daily/weekly/monthly
            # performance keeps measuring trading results only.
            if self.book.day_start_equity > 0:
                self.book.day_start_equity += amount
            if self.book.week_start_equity > 0:
                self.book.week_start_equity += amount
            if self.book.month_start_equity > 0:
                self.book.month_start_equity += amount
            self.book.hwm["total"] += amount
            self.journal.record("capital_sync", {"kind": "contribution", "amount": amount})
            self.alerter.info("capital added to pot", f"${amount:,.2f} now deployable")
            changed = True
        elif target < after_pending - 0.005:
            amount = round(after_pending - target, 2)
            self.book.request_withdrawal(amount)
            self.journal.record("capital_sync", {"kind": "withdrawal_requested", "amount": amount})
            self.alerter.info("withdrawal requested",
                              f"${amount:,.2f} will be freed from pot cash at the next window")
            changed = True
        if changed:
            self.book.save()

    # ------------------------------------------------------------------ lifecycle
    def run(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: setattr(self, "_stop", True))
            except (ValueError, OSError):
                pass
        self.alerter.info("supervisor started",
                          f"mode={self.m.mode} profile={self.m.universe.profile}")
        while not self._stop:
            now = self.now_fn()
            try:
                self.tick(now)
            except Exception as exc:                      # a tick must never kill the process
                import traceback
                self.journal.record("error", {"where": "tick", "err": repr(exc),
                                              "trace": traceback.format_exc()[-1500:]})
                self.alerter.critical("supervisor tick failed", repr(exc)[:500])
            interval = self.m.cadence.fast_loop_seconds if is_rth(now) \
                else self.m.cadence.slow_loop_seconds
            self.sleep(interval)
        self.alerter.info("supervisor stopped", "clean shutdown")

    def run_agent_once(self, run_type: str) -> None:
        """CLI entry: one agent cycle now (fresh news pull first), outside the scheduler."""
        now = self.now_fn()
        if not self._ensure_connected():
            raise RuntimeError("broker not reachable")
        held = set(self.book.positions)
        quotes = self._quotes(held) if held else {}
        fresh = news_poll(self.feeds, self.news.seen, now=now)
        self.news.add(fresh)
        self.news.save()
        universe = [i.symbol for i in self.m.universe.active.instruments]
        self._scored_recent = score_items(self.news.recent(36, now), universe)
        self._sync_external_fills(now)
        self._agent_job(run_type, now)

    # ------------------------------------------------------------------ one pass
    def tick(self, now: datetime) -> None:
        now = utc(now)
        self._heartbeat(now)
        self.sync_capital()
        self._telegram_job(now)                # owner can always reach the agent, even killed
        if self._kill_engaged():
            return
        if not self._ensure_connected():
            return
        self._sync_external_fills(now)

        held = set(self.book.positions)
        quotes = self._quotes(held) if held else {}
        prices = {s: (q.mid or q.last) for s, q in quotes.items() if (q.mid or q.last)}
        snap = None
        if set(prices) >= held:
            snap = self.book.equity(prices, now)
            self.book.update_high_prices(prices)
            self.book.update_hwm(snap)
            self.book.ensure_day(now.astimezone(self.tz).date(), snap.equity)
            self.book.ensure_week(now.astimezone(self.tz).date(), snap.equity)
            self.book.ensure_month(now.astimezone(self.tz).date(), snap.equity)
            self.book.settle_through(now.date())
            self.book.save()
        elif held:
            self.journal.record("warning", {"where": "tick", "msg": "missing quotes for held symbols"})

        self._reconcile()
        if snap is not None:
            self._breakers(snap, quotes, now)
        self._jobs(now, quotes)

    # ------------------------------------------------------------------ plumbing
    def _heartbeat(self, now: datetime) -> None:
        self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        self.heartbeat_path.write_text(now.isoformat(timespec="seconds"), encoding="utf-8")

    def _kill_engaged(self) -> bool:
        engaged = Path(self.m.kill_switch.file).exists()
        if engaged and not self.state.kill_handled:
            n = self.executor.cancel_open_engine_orders()
            self.journal.record("kill_switch", {"cancelled_orders": n})
            self.alerter.critical("KILL SWITCH ENGAGED",
                                  f"{n} open orders cancelled; no new orders until cleared + restart")
            self.state.kill_handled = True
            self.state.save(self.data_dir / "schedule_state.json")
        elif not engaged and self.state.kill_handled:
            self.state.kill_handled = False
            self.state.save(self.data_dir / "schedule_state.json")
        return engaged

    def _ensure_connected(self) -> bool:
        try:
            if self.broker.is_connected():
                return True
            self.broker.connect()
            self.journal.record("broker", {"event": "reconnected"})
            return True
        except Exception as exc:
            self.journal.record("error", {"where": "connect", "err": str(exc)})
            self.alerter.warning("broker connection down", str(exc)[:300])
            return False

    def _sync_external_fills(self, now: datetime) -> None:
        since_txt = self.state.last_fill_sync
        since = utc(datetime.fromisoformat(since_txt)) if since_txt else now - timedelta(days=2)
        self.executor.sync_external_fills(since)
        self.state.last_fill_sync = now.isoformat(timespec="seconds")
        self.state.save(self.data_dir / "schedule_state.json")

    def _quotes(self, symbols: Set[str]) -> Dict[str, Quote]:
        out: Dict[str, Quote] = {}
        for sym in sorted(symbols):
            try:
                out[sym] = self.broker.quote(self._contract(sym))
            except Exception as exc:
                self.journal.record("warning", {"where": "quote", "symbol": sym, "err": str(exc)})
        return out

    def _contract(self, symbol: str) -> Contract:
        inst = self.m.universe.active.instrument(symbol)
        return Contract(symbol=symbol, exchange=inst.exchange, currency=inst.currency) \
            if inst else Contract(symbol=symbol)

    def _bars(self, symbols: Sequence[str], now: datetime) -> Dict[str, List[Bar]]:
        """Daily bars, cached per calendar day (history doesn't change intraday)."""
        day = now.date().isoformat()
        if self._bars_cache_day != day:
            self._bars_cache, self._bars_cache_day = {}, day
        out: Dict[str, List[Bar]] = {}
        for sym in symbols:
            if sym not in self._bars_cache:
                try:
                    self._bars_cache[sym] = self.broker.daily_bars(self._contract(sym), BARS_FOR_STATS)
                except Exception as exc:
                    self.journal.record("warning", {"where": "bars", "symbol": sym, "err": str(exc)})
                    continue
            out[sym] = self._bars_cache[sym]
        return out

    def _reconcile(self) -> None:
        try:
            broker_positions = self.broker.positions()
        except Exception as exc:
            self.journal.record("error", {"where": "reconcile", "err": str(exc)})
            return
        mismatches = self.book.reconcile(broker_positions, dedicated=self.m.account.dedicated)
        if mismatches and not self.book.frozen:
            detail = "; ".join(f"{x.symbol} book={x.book_qty} broker={x.broker_qty} ({x.kind})"
                               for x in mismatches)
            self.book.freeze(f"reconcile mismatch: {detail}"[:300])
            self.book.save()
            self.journal.record("freeze", {"reason": detail})
            self.alerter.critical("RECONCILE MISMATCH - engine frozen", detail[:800])

    def _breakers(self, snap, quotes: Dict[str, Quote], now: datetime) -> None:
        state = evaluate_breakers(self.m, self.book, snap)
        today = now.astimezone(self.tz).date()
        for sleeve in state.paused_sleeves:
            if not self.book.is_sleeve_paused(sleeve, today):
                until = sleeve_pause_until(today)
                self.book.pause_sleeve(sleeve, until)
                self.journal.record("breaker", {"sleeve": sleeve, "until": until.isoformat()})
                self.alerter.warning(f"{sleeve} sleeve paused", f"until {until}")
        if state.pause_all_entries and not self.book.entries_paused(today):
            self.book.pause_entries(today, "daily loss limit")
            self.journal.record("breaker", {"pause": "daily", "until": today.isoformat()})
            self.alerter.warning("daily loss limit hit", "no new entries for the rest of today")
        if state.pause_entries_until and state.pause_entries_until > \
                (date.fromisoformat(self.book.entries_paused_until) if self.book.entries_paused_until
                 else date.min):
            self.book.pause_entries(state.pause_entries_until, state.pause_entries_reason)
            self.journal.record("breaker", {"pause": state.pause_entries_reason,
                                            "until": state.pause_entries_until.isoformat()})
            self.alerter.warning("entries paused", f"{state.pause_entries_reason} — "
                                                   f"until {state.pause_entries_until}")
        if state.halt and not self.book.halted:
            self.book.halt("; ".join(state.reasons)[:300])
            self.journal.record("halt", {"reasons": state.reasons})
            self.alerter.critical("TOTAL DRAWDOWN HALT",
                                  "active sleeves are being liquidated; restart requires human")
            self._liquidate_active(quotes)
        self.book.save()

    def _liquidate_active(self, quotes: Dict[str, Quote]) -> None:
        from ibagent.sleeves import ProtectiveAction
        actions = [ProtectiveAction("time_stop", p.symbol, p.sleeve, sell_qty=p.qty,
                                    reason="drawdown halt liquidation")
                   for p in self.book.positions.values() if p.sleeve != "core" and p.qty > 0]
        missing = [a.symbol for a in actions if a.symbol not in quotes]
        if missing:
            quotes = {**quotes, **self._quotes(set(missing))}
        self.executor.execute_protective(actions, quotes)

    # ------------------------------------------------------------------ scheduled jobs
    def _jobs(self, now: datetime, quotes: Dict[str, Quote]) -> None:
        local = now.astimezone(self.tz)
        today = local.date()
        hhmm = local.strftime("%H:%M")
        c = self.m.cadence

        if now.timestamp() - self.state.last_news_poll_ts >= c.news_poll_seconds:
            self._news_job(now, quotes)

        if is_trading_day(today) and is_rth(now) \
                and now.timestamp() - self.state.last_protective_ts >= PROTECTIVE_MIN_SPACING_S:
            self._protective_job(now, quotes)

        if is_trading_day(today) and is_rth(now) \
                and now.timestamp() - self.state.last_status_ts >= STATUS_UPDATE_SPACING_S:
            self._status_update(now)

        weekday = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")[local.weekday()]
        if is_trading_day(today) and weekday == c.weekly_review.day \
                and hhmm >= c.weekly_review.time and self.state.last_weekly != _monday(today):
            self.state.last_weekly = _monday(today)
            self.state.save(self.data_dir / "schedule_state.json")
            self._agent_job("weekly", now)

        if is_trading_day(today) and hhmm >= c.daily_check.time \
                and self.state.last_daily != today.isoformat():
            self.state.last_daily = today.isoformat()
            self.state.save(self.data_dir / "schedule_state.json")
            self._agent_job("daily", now)

        # Core rebalance needs the MARKET OPEN (DAY limit orders): late morning, inside RTH.
        if is_trading_day(today) and is_rth(now) and "10:00" <= hhmm <= "15:30":
            self._maybe_rebalance(now)

        if is_trading_day(today) and hhmm >= c.daily_report.time \
                and self.state.last_report != today.isoformat():
            self.state.last_report = today.isoformat()
            self.state.save(self.data_dir / "schedule_state.json")
            self._report_job(now)

    def _news_job(self, now: datetime, quotes: Dict[str, Quote]) -> None:
        self.state.last_news_poll_ts = now.timestamp()
        self.state.save(self.data_dir / "schedule_state.json")
        fresh = news_poll(self.feeds, self.news.seen, now=now)
        self.news.add(fresh)
        self.news.save()
        universe = [i.symbol for i in self.m.universe.active.instruments]
        self._scored_recent = score_items(self.news.recent(36, now), universe)
        held = set(self.book.positions)
        # Any whitelisted symbol carrying material news is watchable — catalysts should not
        # need the model to have predicted them last week. The gate's materiality + price-move
        # + budget/cooldown thresholds still decide whether a run actually fires.
        mentioned = {sym for s in self._scored_recent
                     if s.score >= self.m.cadence.event.min_materiality for sym in s.symbols}
        watched = set(self.state.watchlist) | mentioned
        gate = EventGateState.from_dict(self.state.event_gate)
        need_quotes = (held | watched) - set(quotes)
        if need_quotes:
            quotes = {**quotes, **self._quotes(need_quotes)}
        moves = self._day_moves(held | watched, quotes, now)
        trigger = check_event_gate(self.m.cadence.event, gate, self._scored_recent,
                                   held, watched, moves, now)
        self.state.event_gate = gate.as_dict()
        self.state.save(self.data_dir / "schedule_state.json")
        if trigger and is_rth(now):
            note = (f"# Event trigger\n\nsymbol: {trigger.symbol}\nmateriality: {trigger.score}\n"
                    f"day move: {trigger.move_pct:+.1%}\nheadline: {trigger.headline}\n{trigger.link}\n")
            self.journal.record("event_trigger", {"symbol": trigger.symbol, "score": trigger.score,
                                                  "move": trigger.move_pct, "headline": trigger.headline})
            self._agent_job("event", now, event_note=note)

    def _day_moves(self, symbols: Set[str], quotes: Dict[str, Quote], now: datetime) -> Dict[str, float]:
        moves: Dict[str, float] = {}
        need = [s for s in symbols if s in quotes and (quotes[s].mid or quotes[s].last)]
        bars = self._bars(need, now)
        for sym in need:
            b = bars.get(sym)
            prev = previous_trading_day(now.astimezone(self.tz).date())
            ref = next((bar.close for bar in reversed(b or []) if bar.ts.date() <= prev), None)
            mark = quotes[sym].mid or quotes[sym].last
            if ref and ref > 0 and mark:
                moves[sym] = mark / ref - 1.0
        return moves

    def _protective_job(self, now: datetime, quotes: Dict[str, Quote]) -> None:
        self.state.last_protective_ts = now.timestamp()
        self.state.save(self.data_dir / "schedule_state.json")
        held_active = [p.symbol for p in self.book.positions.values() if p.sleeve != "core"]
        if not held_active:
            return
        q = {**quotes, **self._quotes(set(held_active) - set(quotes))}
        prices = {s: (x.mid or x.last) for s, x in q.items() if (x.mid or x.last)}
        bars = self._bars(held_active, now)
        atrs = {s: a for s, b in bars.items() if (a := calc_atr(b, self.m.risk.stops.atr_period))}
        actions = protective_actions(self.m, self.book, prices, atrs,
                                     now.astimezone(self.tz).date())
        if actions:
            report = self.executor.execute_protective(actions, q)
            self.journal.record("protective", {
                "actions": [f"{a.kind} {a.symbol} qty={a.sell_qty} stop={a.new_stop}" for a in actions],
                "realized": report.realized_pnl, "errors": report.errors})

    def _agent_job(self, run_type: str, now: datetime, event_note: str = "") -> None:
        symbols = self._symbols_for_run(run_type)
        quotes = self._quotes(symbols)
        bars = self._bars(sorted(symbols), now)
        stats = stats_table(bars, self.m.risk.stops.atr_period)
        atrs = {s: v.atr for s, v in stats.items() if v.atr}
        held = set(self.book.positions)
        digest = build_digest(self._scored_recent, held, set(self.state.watchlist))
        result = run_cycle(self.m, self.book, self.journal, self.alerter, self.runner,
                           self.executor, quotes, atrs, stats, digest, run_type, now,
                           self.llm_state_path, event_note=event_note,
                           skills_dir=self.skills_dir,
                           kill_switch=Path(self.m.kill_switch.file).exists())
        if not result.held and result.decision.watchlist:
            self.state.watchlist = result.decision.watchlist
            self.state.save(self.data_dir / "schedule_state.json")

    def _symbols_for_run(self, run_type: str) -> Set[str]:
        held = set(self.book.positions)
        core = set(self.m.universe.active.core_holdings)
        if run_type == "weekly":
            return held | core | {i.symbol for i in self.m.universe.active.instruments}
        return held | core | set(self.state.watchlist)

    def _status_text(self, now: datetime) -> Optional[Tuple[str, str]]:
        """(title, body) for the P&L pulse; shared by the 2h schedule and the `status` command."""
        held = set(self.book.positions)
        quotes = self._quotes(held) if held else {}
        prices = {s: (q.mid or q.last) for s, q in quotes.items() if (q.mid or q.last)}
        try:
            snap = self.book.equity(prices, now)
        except Exception:
            return None
        day_pnl = snap.equity - self.book.day_start_equity if self.book.day_start_equity else 0.0
        day_pct = day_pnl / self.book.day_start_equity if self.book.day_start_equity else 0.0
        total_pnl = snap.equity - self.book.net_contributions
        total_pct = total_pnl / self.book.net_contributions if self.book.net_contributions > 0 else 0.0
        fees_today, _ = self._fees_and_realized_today(now)
        mood = "📈" if day_pnl >= 0 else "📉"
        lines = [
            f"P&L today:     {day_pnl:+,.2f} $  ({day_pct:+.2%})",
            f"  before fees: {day_pnl + fees_today:+,.2f} $",
            f"P&L all-time:  {total_pnl:+,.2f} $  ({total_pct:+.2%})",
            f"Equity ${snap.equity:,.2f} · cash ${snap.pot_cash:,.2f} · "
            f"{len(self.book.positions)} position(s)",
        ]
        if self.book.positions:
            lines += ["", f"{'SYM':<6}{'NOW':>9}{'P&L $':>9}{'P&L %':>8}   STOP"]
            for p in sorted(self.book.positions.values(), key=lambda x: x.symbol):
                mark = prices.get(p.symbol, p.avg_cost)
                pnl = (mark - p.avg_cost) * p.qty
                pct = mark / p.avg_cost - 1.0 if p.avg_cost else 0.0
                stop = f"{p.stop_price:,.2f}" if p.stop_price else "—"
                lines.append(f"{p.symbol:<6}{mark:>9,.2f}{pnl:>+9.2f}{pct:>+8.1%}   {stop}")
        title = (f"{mood} {now.astimezone(self.tz):%H:%M} — "
                 f"{'up' if day_pnl >= 0 else 'down'} {abs(day_pnl):,.2f} $ today")
        return title, "\n".join(lines)

    def _status_update(self, now: datetime) -> None:
        self.state.last_status_ts = now.timestamp()
        self.state.save(self.data_dir / "schedule_state.json")
        st = self._status_text(now)
        if st:
            self.alerter.info(st[0], st[1], dedupe=False)

    # ------------------------------------------------------------------ inbound Telegram
    def _telegram_job(self, now: datetime) -> None:
        if "telegram" not in self.m.alerts.channels:
            return
        token, chat = get_secret("TELEGRAM_BOT_TOKEN"), get_secret("TELEGRAM_CHAT_ID")
        if not token or not chat:
            return
        offset, texts = tg_poll(token, chat, self.state.telegram_offset)
        if offset != self.state.telegram_offset:
            self.state.telegram_offset = offset
            self.state.save(self.data_dir / "schedule_state.json")
        for text in texts:
            try:
                self._handle_owner_message(text, now)
            except Exception as exc:
                self.journal.record("error", {"where": "telegram_handle", "err": repr(exc)})
                self.alerter.info("💬 sorry", f"couldn't process that: {exc}", dedupe=False)

    def _handle_owner_message(self, text: str, now: datetime) -> None:
        kind = classify(text)
        self.journal.record("owner_message", {"text": text[:300], "kind": kind})
        if kind in ("command:status", "command:pnl", "command:positions"):
            st = self._status_text(now)
            if st:
                self.alerter.info(st[0], st[1], dedupe=False)
            else:
                self.alerter.info("💬 status unavailable", "cannot mark the book right now "
                                  "(missing prices); try again in a minute", dedupe=False)
        elif kind == "command:report":
            self._report_job(now)
        elif kind == "command:help":
            self.alerter.info("ℹ️ Agent commands", HELP_TEXT, dedupe=False)
        else:
            self._qa_job(text, now)

    def _qa_job(self, question: str, now: datetime) -> None:
        """Answer a free-text owner question with a read-only Claude run. Counts against the
        daily invocation cap; can never trade — there is no decision/order path from here."""
        state = LLMState.load(self.llm_state_path)
        today = now.date().isoformat()
        if state.day != today:
            state.day, state.count = today, 0
        if state.count >= self.m.llm.daily_invocation_cap:
            self.alerter.info("💬 out of AI budget for today",
                              f"the daily cap of {self.m.llm.daily_invocation_cap} runs is used up; "
                              "commands like `status` still work", dedupe=False)
            return
        state.count += 1
        state.runs_total += 1
        state.save(self.llm_state_path)
        self.alerter.info("💬 on it", "researching your question — this can take a minute or two",
                          dedupe=False)
        from ibagent.llm.runner import ClaudeCodeRunner, RunRequest, default_runs_root
        runs_root = default_runs_root(self.m.llm.sandbox.runs_root)
        bundle_dir = runs_root / f"{now:%Y%m%d-%H%M%S}-qa"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        held = set(self.book.positions)
        quotes = self._quotes(held) if held else {}
        prices = {s: (q.mid or q.last) for s, q in quotes.items() if (q.mid or q.last)}
        try:
            snap = self.book.equity(prices, now)
            from ibagent.agent.bundle import portfolio_json
            (bundle_dir / "portfolio.json").write_text(
                json.dumps(portfolio_json(self.book, snap, self.m), indent=1), encoding="utf-8")
        except Exception:
            (bundle_dir / "portfolio.json").write_text("{}", encoding="utf-8")
        (bundle_dir / "question.md").write_text(question, encoding="utf-8")
        runner = ClaudeCodeRunner(self.m.llm, schema_text=None)
        prompt = ("You are the assistant for the owner of this small trading system. "
                  "question.md is the owner's question; portfolio.json is the current book. "
                  "Answer briefly and concretely (under 250 words, plain text, no markdown "
                  "tables). Use WebSearch/WebFetch if the question needs current information. "
                  "You cannot trade or change anything - if asked to trade, explain that "
                  "decisions happen in the scheduled runs under the mandate.")
        res = runner.run(RunRequest(run_type="daily", bundle_dir=bundle_dir, prompt=prompt))
        answer = (res.text or "").strip() or f"(no answer: {res.error})"
        self.journal.record("qa", {"question": question[:300], "ok": res.ok,
                                   "duration_s": res.duration_s, "error": (res.error or "")[:400]})
        if self.m.journal.keep_raw_llm_output and (res.raw_stdout or res.raw_stderr):
            stamp = f"{now:%Y%m%d-%H%M%S}-qa"
            self.journal.save_blob(f"{stamp}-stdout.txt", res.raw_stdout or "")
            if res.raw_stderr:
                self.journal.save_blob(f"{stamp}-stderr.txt", res.raw_stderr)
        self.alerter.info("💬 answer", answer[:3500], dedupe=False)

    def _report_job(self, now: datetime) -> None:
        held = set(self.book.positions) | set(self.m.universe.active.core_holdings)
        quotes = self._quotes(held)
        prices = {s: (q.mid or q.last) for s, q in quotes.items() if (q.mid or q.last)}
        try:
            snap = self.book.equity(prices, now)
        except Exception as exc:
            self.alerter.warning("daily report skipped", str(exc)[:200])
            return
        day_pnl = snap.equity - self.book.day_start_equity if self.book.day_start_equity else 0.0
        day_pct = day_pnl / self.book.day_start_equity if self.book.day_start_equity else 0.0
        since_start = snap.equity - self.book.net_contributions
        since_pct = since_start / self.book.net_contributions if self.book.net_contributions > 0 else 0.0
        fees_today, realized_today = self._fees_and_realized_today(now)
        mood = "📈" if day_pnl >= 0 else "📉"

        # ---- plain-language summary first -------------------------------------------------
        lines = [
            f"P&L today:     {day_pnl:+,.2f} $ ({day_pct:+.2%})",
            f"  before fees: {day_pnl + fees_today:+,.2f} $   (fees paid today: {fees_today:,.2f} $)",
            f"P&L all-time:  {since_start:+,.2f} $ ({since_pct:+.2%}) on "
            f"${self.book.net_contributions:,.0f} put in",
        ]
        if realized_today:
            lines.append(f"Locked in today (closed trades): {realized_today:+,.2f} $")

        # ---- per-stock rundown: how each holding moved TODAY ------------------------------
        if self.book.positions:
            bars = self._bars(sorted(self.book.positions), now)
            lines += ["", "How each stock did today:"]
            for p in sorted(self.book.positions.values(), key=lambda x: x.symbol):
                mark = prices.get(p.symbol, p.avg_cost)
                prev = self._prev_close(bars.get(p.symbol), now)
                base = prev if prev and p.entry_date < now.astimezone(self.tz).date().isoformat() \
                    else p.avg_cost                      # entered today: measure from entry
                day_move = (mark - base) * p.qty
                day_move_pct = mark / base - 1.0 if base else 0.0
                total = (mark - p.avg_cost) * p.qty
                lines.append(f"• {p.symbol}: {day_move:+,.2f} $ today ({day_move_pct:+.1%}) · "
                             f"total {total:+,.2f} $ since entry")
        watch = self._watch_outs(prices, now)
        lines.append("")
        if watch:
            lines.append("Watch out:")
            lines += [f"• {w}" for w in watch]
        else:
            lines.append("Nothing needs your attention. ✅")

        # ---- details ----------------------------------------------------------------------
        lines += ["", "— details —",
                  f"Equity ${snap.equity:,.2f} · cash ${snap.pot_cash:,.2f} "
                  f"(settled ${snap.settled_pot_cash:,.2f})",
                  f"Sleeves: core ${snap.sleeve_value['core']:,.0f} · trend "
                  f"${snap.sleeve_value['trend']:,.0f} · spec ${snap.sleeve_value['spec']:,.0f}"]
        if self.book.positions:
            lines += ["", f"{'SYM':<6}{'SLEEVE':<7}{'QTY':>8}{'AVG':>9}{'NOW':>9}{'P&L':>9}  STOP"]
            for p in sorted(self.book.positions.values(), key=lambda x: x.symbol):
                mark = prices.get(p.symbol, p.avg_cost)
                pnl = (mark - p.avg_cost) * p.qty
                stop = f"{p.stop_price:.2f}" if p.stop_price else "—"
                lines.append(f"{p.symbol:<6}{p.sleeve:<7}{p.qty:>8g}{p.avg_cost:>9.2f}"
                             f"{mark:>9.2f}{pnl:>+9.2f}  {stop}")
        else:
            lines += ["", "no open positions"]
        body = "\n".join(lines)
        self.journal.record("daily_report", {"equity": snap.equity, "text": body})
        self.alerter.info(f"{mood} Daily report — {now.astimezone(self.tz):%a %b %d}", body)

    def _fees_and_realized_today(self, now: datetime) -> tuple[float, float]:
        """Sum commissions and realized P&L from today's fills (market-timezone day)."""
        today = now.astimezone(self.tz).date().isoformat()
        fees = realized = 0.0
        for e in self.journal.iter(kinds=("fill",)):
            p = e.get("payload", {})
            if str(p.get("ts", e.get("ts", "")))[:10] == today:
                fees += float(p.get("commission", 0.0) or 0.0)
                r = p.get("realized")
                if isinstance(r, (int, float)):
                    realized += r
        return round(fees, 2), round(realized, 2)

    @staticmethod
    def _prev_close(bars: Optional[List[Bar]], now: datetime) -> Optional[float]:
        if not bars:
            return None
        today = now.date()
        for b in reversed(bars):
            if b.ts.date() < today:
                return b.close
        return None

    def _watch_outs(self, prices: Dict[str, float], now: datetime) -> List[str]:
        """Plain-language flags a non-technical reader should act on or know about."""
        out: List[str] = []
        if self.book.halted:
            out.append("TRADING IS HALTED (big drawdown) — everything moved to safety; "
                       "restarting needs you.")
        if self.book.frozen:
            out.append("Engine is FROZEN: the book and IBKR disagree — check the account.")
        if Path(self.m.kill_switch.file).exists():
            out.append("Kill switch is engaged — the agent is not trading.")
        today = now.astimezone(self.tz).date()
        for sleeve, until in sorted(self.book.paused_sleeves.items()):
            if self.book.is_sleeve_paused(sleeve, today):
                out.append(f"The {sleeve} strategy is paused (losses) until {until}.")
        if self.book.entries_paused(today):
            out.append(f"New buying is paused until {self.book.entries_paused_until} "
                       f"({self.book.entries_paused_reason}).")
        if self.book.consecutive_spec_losers >= 3:
            out.append(f"{self.book.consecutive_spec_losers} speculative trades lost in a row.")
        for p in sorted(self.book.positions.values(), key=lambda x: x.symbol):
            mark = prices.get(p.symbol)
            if mark and p.stop_price and mark > 0 and (mark - p.stop_price) / mark <= 0.03:
                out.append(f"{p.symbol} is within 3% of its safety exit (stop {p.stop_price:.2f}) — "
                           "it may be sold automatically soon.")
            if p.time_stop_date:
                from ibagent.marketclock import trading_days_between
                left = trading_days_between(today, date.fromisoformat(p.time_stop_date))
                if 0 <= left <= 2:
                    out.append(f"{p.symbol} reaches its time limit in {left} trading day(s) — "
                               "it will be sold if the idea hasn't worked.")
        return out

    def _maybe_rebalance(self, now: datetime) -> None:
        """Bring the core sleeve to target. The period is marked done ONLY when every intent
        fills (or nothing needed doing) — an unfilled/errored attempt retries the next RTH
        window with freshly recomputed diffs, instead of silently skipping to next month."""
        local = now.astimezone(self.tz)
        period = local.strftime("%Y-%m") if self.m.sleeves.rebalance == "monthly" \
            else _monday(local.date())
        if self.state.last_rebalance_period == period or self.book.halted or self.book.frozen:
            return
        core = set(self.m.universe.active.core_holdings) | set(self.book.positions)
        quotes = self._quotes(core)
        prices = {s: (q.mid or q.last) for s, q in quotes.items() if (q.mid or q.last)}
        missing_core = set(self.m.universe.active.core_holdings) - set(prices)
        if missing_core:
            self.journal.record("warning", {"where": "rebalance",
                                            "err": f"no quotes for {sorted(missing_core)}"})
            return                                        # retry next window, period NOT consumed
        try:
            snap = self.book.equity(prices, now)
        except Exception as exc:
            self.journal.record("warning", {"where": "rebalance", "err": str(exc)})
            return
        intents, sweep = core_rebalance(self.m, self.book, snap, prices, local.date())
        if not intents:
            self.state.last_rebalance_period = period     # in band: genuinely nothing to do
            self.state.save(self.data_dir / "schedule_state.json")
            return
        report = self.executor.execute_rebalance(intents, quotes)
        complete = report.filled == len(intents) and not report.errors
        if complete:
            self.state.last_rebalance_period = period
            self.state.save(self.data_dir / "schedule_state.json")
            if sweep > 0:
                self.book.spec_profit_since_sweep = 0.0
                self.book.save()
        self.journal.record("rebalance", {
            "intents": [f"{i.side} {i.symbol} ${i.usd:.2f}" for i in intents],
            "filled": report.filled, "complete": complete,
            "sweep": sweep, "errors": report.errors})
        self.alerter.info("🏦 core rebalance" + ("" if complete else " (partial — will retry)"),
                          "\n".join(f"{i.side} {i.symbol} ${i.usd:.2f}" for i in intents),
                          dedupe=False)
