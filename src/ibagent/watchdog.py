"""Watchdog: a tiny separate process run by Task Scheduler every few minutes.

Reads the supervisor's heartbeat file; if it is stale (or missing while a book exists),
alerts you — WITH HYSTERESIS: one 🚨 when the outage starts, at most one reminder per hour
while it lasts, and one ✅ when it recovers. (Without this, a 5-minute schedule turned every
outage — including deliberate restarts and the PC sleeping — into an alert flood.)

It never touches the broker or the book — its only job is telling you the supervisor died
while GTC stops at IBKR keep protecting the positions.

Exit codes (for Task Scheduler history): 0 healthy, 1 stale/missing heartbeat.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ibagent.alerts import Alerter, build_alerter
from ibagent.config import Mandate
from ibagent.marketclock import utc

HEARTBEAT = Path("data") / "heartbeat.txt"
BOOK = Path("data") / "book.json"
STATE = Path("data") / "watchdog_state.json"
REMINDER_S = 3600.0


def _load_state(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(path: Path, d: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(d), encoding="utf-8")
    except OSError:
        pass                                              # state loss only risks an extra alert


def check(m: Mandate, heartbeat_path: Path = HEARTBEAT, book_path: Path = BOOK,
          now: datetime | None = None, alerter: Alerter | None = None,
          state_path: Path = STATE) -> int:
    now = utc(now or datetime.now(timezone.utc))
    alerter = alerter or build_alerter(m.alerts)
    stale_s = m.alerts.heartbeat_stale_minutes * 60
    state = _load_state(state_path)

    problem = ""
    if not heartbeat_path.exists():
        if not book_path.exists():
            return 0                                      # never started: nothing to guard yet
        problem = "book exists but no heartbeat file; is the supervisor running?"
    else:
        try:
            ts = utc(datetime.fromisoformat(heartbeat_path.read_text(encoding="utf-8").strip()))
            age = (now - ts).total_seconds()
            if age > stale_s:
                problem = (f"last beat {age / 60:.0f} min ago "
                           f"(limit {m.alerts.heartbeat_stale_minutes} min)")
        except ValueError:
            problem = f"heartbeat file unreadable: {heartbeat_path}"

    if not problem:
        if state.get("stale_since"):
            alerter.info("✅ supervisor is back",
                         f"heartbeat healthy again (was down since {state['stale_since'][:16]})",
                         dedupe=False)
        _save_state(state_path, {})
        return 0

    if not state.get("stale_since"):                      # NEW outage: one loud alert
        alerter.critical("🚨 supervisor down",
                         f"{problem}. Your positions stay protected by the GTC stops at IBKR. "
                         "I'll remind you hourly until it's back.")
        _save_state(state_path, {"stale_since": now.isoformat(timespec="seconds"),
                                 "last_alert_ts": now.timestamp()})
    elif now.timestamp() - float(state.get("last_alert_ts", 0)) >= REMINDER_S:
        alerter.warning("supervisor still down",
                        f"{problem} (down since {state['stale_since'][:16]})", )
        state["last_alert_ts"] = now.timestamp()
        _save_state(state_path, state)
    return 1


def main(m: Mandate) -> int:
    return check(m)
