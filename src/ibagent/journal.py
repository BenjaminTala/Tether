"""Append-only journal. Every decision, order, fill, alert, freeze and LLM run is recorded.

Layout:  <dir>/YYYY-MM.jsonl   one JSON object per line: {"ts", "kind", "payload"}
         <dir>/blobs/<name>    raw artifacts (LLM stdout/stderr, context bundles), if enabled
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set

_SAFE_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Journal:
    def __init__(self, directory: Path | str):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def record(self, kind: str, payload: Dict[str, Any], ts: Optional[datetime] = None) -> Dict[str, Any]:
        if not kind or not isinstance(payload, dict):
            raise ValueError("kind must be non-empty and payload a dict")
        ts = ts or utcnow()
        entry = {"ts": ts.isoformat(timespec="seconds"), "kind": kind, "payload": payload}
        path = self.dir / f"{ts:%Y-%m}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, separators=(",", ":"), default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return entry

    def iter(self, since: Optional[datetime] = None, kinds: Optional[Iterable[str]] = None) -> Iterator[Dict[str, Any]]:
        want: Optional[Set[str]] = set(kinds) if kinds else None
        for path in sorted(self.dir.glob("*.jsonl")):
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # a torn line must never take the engine down
                    if want and entry.get("kind") not in want:
                        continue
                    if since and entry.get("ts", "") < since.isoformat(timespec="seconds"):
                        continue
                    yield entry

    def tail(self, n: int, kinds: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        return list(self.iter(kinds=kinds))[-n:]

    def save_blob(self, name: str, content: str) -> Path:
        safe = "".join(c if c in _SAFE_CHARS else "_" for c in name)[:120]
        blobs = self.dir / "blobs"
        blobs.mkdir(exist_ok=True)
        path = blobs / safe
        path.write_text(content, encoding="utf-8")
        return path
