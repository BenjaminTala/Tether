"""Capital ledger — the customisable "pot" boundary.

The pot is defined by an append-only ledger of human capital events. The engine never writes
to it (no automatic top-ups). Pot accounting elsewhere:

    pot_cash   = net_contributions - sum(buys) + sum(sells) - fees
    pot_equity = pot_cash + market value of engine-owned positions

The engine may deploy at most pot_cash (and never more than the account's settled cash).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

EventKind = Literal["seed", "add", "withdraw"]
_KINDS = ("seed", "add", "withdraw")


class LedgerError(ValueError):
    """Invalid ledger operation or corrupt ledger file."""


@dataclass(frozen=True)
class CapitalEvent:
    ts: str
    kind: EventKind
    amount_usd: float
    note: str = ""
    by: str = "human"

    @staticmethod
    def from_dict(d: dict, line_no: int) -> "CapitalEvent":
        try:
            ev = CapitalEvent(ts=str(d["ts"]), kind=d["kind"], amount_usd=float(d["amount_usd"]),
                              note=str(d.get("note", "")), by=str(d.get("by", "human")))
        except (KeyError, TypeError, ValueError) as exc:
            raise LedgerError(f"ledger line {line_no}: malformed event ({exc})") from exc
        if ev.kind not in _KINDS or ev.amount_usd <= 0:
            raise LedgerError(f"ledger line {line_no}: invalid kind/amount")
        return ev

    @property
    def signed(self) -> float:
        return -self.amount_usd if self.kind == "withdraw" else self.amount_usd


class CapitalLedger:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    # ---- reads ----
    def events(self) -> List[CapitalEvent]:
        if not self.path.exists():
            return []
        out: List[CapitalEvent] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(CapitalEvent.from_dict(json.loads(line), n))
                except json.JSONDecodeError as exc:
                    raise LedgerError(f"ledger line {n}: not JSON") from exc
        if out and (out[0].kind != "seed" or any(e.kind == "seed" for e in out[1:])):
            raise LedgerError("ledger must start with exactly one seed event")
        return out

    def is_initialized(self) -> bool:
        return bool(self.events())

    def seed(self) -> Optional[float]:
        ev = self.events()
        return ev[0].amount_usd if ev else None

    def net_contributions(self) -> float:
        """Seed + adds - withdrawals. Can go negative if you withdrew more than you put in (profit)."""
        return round(sum(e.signed for e in self.events()), 2)

    # ---- writes (human-initiated only) ----
    def init_seed(self, amount_usd: float, note: str = "", by: str = "human") -> CapitalEvent:
        if self.is_initialized():
            raise LedgerError("ledger already initialized; use add/withdraw to change capital")
        return self._append("seed", amount_usd, note, by)

    def add(self, amount_usd: float, note: str = "", by: str = "human") -> CapitalEvent:
        self._require_initialized()
        return self._append("add", amount_usd, note, by)

    def withdraw(self, amount_usd: float, note: str = "", by: str = "human") -> CapitalEvent:
        """Records the intent. The engine satisfies it from pot cash (selling pro-rata from active
        sleeves, then core, at the next window) and only then reports it complete."""
        self._require_initialized()
        return self._append("withdraw", amount_usd, note, by)

    # ---- internals ----
    def _require_initialized(self) -> None:
        if not self.is_initialized():
            raise LedgerError("ledger not initialized; run `ibagent capital init --seed <usd>` first")

    def _append(self, kind: EventKind, amount_usd: float, note: str, by: str) -> CapitalEvent:
        if not isinstance(amount_usd, (int, float)) or amount_usd <= 0:
            raise LedgerError("amount_usd must be a positive number")
        if by != "human":
            raise LedgerError("only humans may write capital events")
        ev = CapitalEvent(ts=datetime.now(timezone.utc).isoformat(timespec="seconds"), kind=kind,
                          amount_usd=round(float(amount_usd), 2), note=note.strip()[:200], by=by)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(ev), separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return ev
