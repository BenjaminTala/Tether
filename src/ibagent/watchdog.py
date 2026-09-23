"""Watchdog: a tiny separate process run by Task Scheduler every few minutes.

Reads the supervisor's heartbeat file; if it is stale (or missing while a book exists),
alerts you — WITH HYSTERESIS: one 🚨 when the outage starts, at most one reminder per hour
while it lasts, and one ✅ when it recovers. (Without this, a 5-minute schedule turned every
outage — including deliberate restarts and the PC sleeping — into an alert flood.)

It never touches the broker or the book — its only job is telling you the supervisor died
while GTC stops at IBKR keep protecting the positions.

Every transition (down / hourly reminder / recovered) is also appended to the journal as a
`watchdog` line, because the state file is wiped on recovery and a Telegram message is not
an audit trail: without this, "did the watchdog fire during the 21:08 wedge?" could only be
answered by the owner's phone (2026-08-25). The journal write is best-effort — an OneDrive
lock must never stop the alert.

The shadow variants (data-shadows/<name>/heartbeat.txt) are checked too, as ONE episode
with its own hysteresis and a warning rather than a 🚨: a dead shadow risks no money, but on
2026-09-22 all six were stopped for a redeploy at 22:42 UTC, never restarted, and sat dead
through the whole 09-23 session while this watchdog — main-only until then — reported
healthy and nobody was told.

Exit codes (for Task Scheduler history): 0 healthy, 1 stale/missing heartbeat.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ibagent.alerts import Alerter, build_alerter
from ibagent.config import Mandate
from ibagent.journal import Journal
from ibagent.marketclock import utc

HEARTBEAT = Path("data") / "heartbeat.txt"
BOOK = Path("data") / "book.json"
STATE = Path("data") / "watchdog_state.json"
SHADOWS = Path("data-shadows")
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


def _journal(journal_dir: Path, now: datetime, payload: dict) -> None:
    try:
        Journal(journal_dir).record("watchdog", payload, ts=now)
    except (OSError, ValueError):
        pass                                              # alerting is the job; the record is a bonus


def _down_minutes(state: dict, now: datetime) -> float | None:
    try:
        since = utc(datetime.fromisoformat(state["stale_since"]))
        return round((now - since).total_seconds() / 60, 1)
    except (KeyError, ValueError, TypeError):
        return None


def _stale_shadows(root: Path, now: datetime, stale_s: float) -> list[str]:
    """Shadow variants whose supervisor is not beating. A variant counts once it has a
    book.json (a never-started one has nothing to guard); an unreadable heartbeat is down."""
    out: list[str] = []
    for book in sorted(root.glob("*/book.json")):
        hb = book.parent / "heartbeat.txt"
        try:
            ts = utc(datetime.fromisoformat(hb.read_text(encoding="utf-8").strip()))
        except (OSError, ValueError):
            out.append(f"{book.parent.name} (no heartbeat)")
            continue
        age = (now - ts).total_seconds()
        if age > stale_s:
            out.append(f"{book.parent.name} (last beat {age / 60:.0f} min ago)")
    return out


def _check_shadows(now: datetime, stale_s: float, root: Path, state: dict,
                   state_path: Path, alerter: Alerter, journal_dir: Path) -> int:
    """Same episode logic as main, under its own state keys so the two never reset each
    other; a shadow outage is a warning (sims, no broker exposure), never a 🚨."""
    down = _stale_shadows(root, now, stale_s)
    if not down:
        if state.get("shadows_since"):
            alerter.info("✅ shadow supervisors are back",
                         f"all shadows beating again (down since {state['shadows_since'][:16]})",
                         dedupe=False)
            _journal(journal_dir, now, {"event": "shadows_recovered",
                                        "since": state["shadows_since"],
                                        "down_minutes": _down_minutes(
                                            {"stale_since": state["shadows_since"]}, now)})
            state.pop("shadows_since", None)
            state.pop("shadows_alert_ts", None)
            _save_state(state_path, state)
        return 0
    problem = ", ".join(down)
    if not state.get("shadows_since"):
        alerter.warning("⚠️ shadow supervisors down",
                        f"{problem}. Shadows are paper sims — nothing at the broker is "
                        "affected — but their A/B record has a hole until each task is "
                        "started again (Start-ScheduledTask IBAgent-Shadow-<name>). "
                        "I'll remind you hourly.")
        state["shadows_since"] = now.isoformat(timespec="seconds")
        state["shadows_alert_ts"] = now.timestamp()
        _save_state(state_path, state)
        _journal(journal_dir, now, {"event": "shadows_down", "problem": problem})
    elif now.timestamp() - float(state.get("shadows_alert_ts", 0)) >= REMINDER_S:
        alerter.warning("shadow supervisors still down",
                        f"{problem} (down since {state['shadows_since'][:16]})")
        state["shadows_alert_ts"] = now.timestamp()
        _save_state(state_path, state)
        _journal(journal_dir, now, {"event": "shadows_reminder", "problem": problem,
                                    "down_minutes": _down_minutes(
                                        {"stale_since": state["shadows_since"]}, now)})
    return 1


def check(m: Mandate, heartbeat_path: Path = HEARTBEAT, book_path: Path = BOOK,
          now: datetime | None = None, alerter: Alerter | None = None,
          state_path: Path = STATE, journal_dir: Path | None = None,
          shadows_root: Path = SHADOWS) -> int:
    now = utc(now or datetime.now(timezone.utc))
    alerter = alerter or build_alerter(m.alerts)
    journal_dir = Path(journal_dir or m.journal.dir)
    stale_s = m.alerts.heartbeat_stale_minutes * 60
    state = _load_state(state_path)
    rc = _check_main(m, now, stale_s, heartbeat_path, book_path, state, state_path,
                     alerter, journal_dir)
    # main's verdict is final and already saved; the shadows re-read the state so a main
    # recovery (which clears main's keys) and a shadow episode never overwrite each other
    return max(rc, _check_shadows(now, stale_s, shadows_root, _load_state(state_path),
                                  state_path, alerter, journal_dir))


def _check_main(m: Mandate, now: datetime, stale_s: float, heartbeat_path: Path,
                book_path: Path, state: dict, state_path: Path, alerter: Alerter,
                journal_dir: Path) -> int:
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
            _journal(journal_dir, now, {"event": "recovered", "since": state["stale_since"],
                                        "down_minutes": _down_minutes(state, now)})
        state.pop("stale_since", None)                    # keep any shadow episode's keys
        state.pop("last_alert_ts", None)
        _save_state(state_path, state)
        return 0

    if not state.get("stale_since"):                      # NEW outage: one loud alert
        alerter.critical("🚨 supervisor down",
                         f"{problem}. Your positions stay protected by the GTC stops at IBKR. "
                         "I'll remind you hourly until it's back.")
        state.update({"stale_since": now.isoformat(timespec="seconds"),
                      "last_alert_ts": now.timestamp()})   # update, not replace: shadow keys stay
        _save_state(state_path, state)
        _journal(journal_dir, now, {"event": "down", "problem": problem})
    elif now.timestamp() - float(state.get("last_alert_ts", 0)) >= REMINDER_S:
        alerter.warning("supervisor still down",
                        f"{problem} (down since {state['stale_since'][:16]})", )
        state["last_alert_ts"] = now.timestamp()
        _save_state(state_path, state)
        _journal(journal_dir, now, {"event": "reminder", "problem": problem,
                                    "down_minutes": _down_minutes(state, now)})
    return 1


def main(m: Mandate) -> int:
    return check(m)
