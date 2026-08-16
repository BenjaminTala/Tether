"""Watchdog: a tiny separate process run by Task Scheduler every few minutes.

Reads the supervisor's heartbeat file; if it is stale (or missing while a book exists),
alerts you. It never touches the broker or the book — its only job is telling you the
supervisor died while GTC stops at IBKR keep protecting the positions.

Exit codes (for Task Scheduler history): 0 healthy, 1 stale/missing heartbeat.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ibagent.alerts import Alerter, build_alerter
from ibagent.config import Mandate
from ibagent.marketclock import utc

HEARTBEAT = Path("data") / "heartbeat.txt"
BOOK = Path("data") / "book.json"


def check(m: Mandate, heartbeat_path: Path = HEARTBEAT, book_path: Path = BOOK,
          now: datetime | None = None, alerter: Alerter | None = None) -> int:
    now = utc(now or datetime.now(timezone.utc))
    alerter = alerter or build_alerter(m.alerts)
    stale_s = m.alerts.heartbeat_stale_minutes * 60
    if not heartbeat_path.exists():
        if book_path.exists():
            alerter.critical("supervisor heartbeat MISSING",
                             "book exists but no heartbeat file; is the supervisor running?")
            return 1
        return 0                                          # never started: nothing to guard yet
    try:
        ts = utc(datetime.fromisoformat(heartbeat_path.read_text(encoding="utf-8").strip()))
    except ValueError:
        alerter.critical("supervisor heartbeat UNREADABLE", str(heartbeat_path))
        return 1
    age = (now - ts).total_seconds()
    if age > stale_s:
        alerter.critical("supervisor heartbeat STALE",
                         f"last beat {age / 60:.0f} min ago (limit {m.alerts.heartbeat_stale_minutes}); "
                         "GTC stops at IBKR still protect positions. Restart the Supervisor task.")
        return 1
    return 0


def main(m: Mandate) -> int:
    return check(m)
