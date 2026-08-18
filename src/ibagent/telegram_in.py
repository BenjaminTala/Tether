"""Inbound Telegram: lets the owner talk BACK to the agent from the phone.

The supervisor polls getUpdates each tick (non-blocking). Only messages from the configured
TELEGRAM_CHAT_ID are honored — anything else is dropped unanswered. Commands are answered
deterministically by the engine; any other text becomes a read-only Claude Q&A run whose
reply goes back to Telegram. Nothing arriving through this channel can place, modify or
cancel an order: there is no code path from here to the broker.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

FETCH_TIMEOUT_S = 10
COMMANDS = ("status", "pnl", "positions", "report", "help")

HELP_TEXT = (
    "Commands I answer instantly:\n"
    "• status / pnl / positions — current P&L and holdings\n"
    "• report — full daily-style report now\n"
    "• help — this message\n\n"
    "Anything else you type is treated as a question and answered by the AI "
    "(may take a minute). I cannot take trade orders here — the mandate decides trades."
)


@dataclass(frozen=True)
class InboundMessage:
    update_id: int
    chat_id: str
    text: str


def default_fetcher(token: str, offset: int) -> bytes:
    params = urllib.parse.urlencode({"offset": offset, "timeout": 0,
                                     "allowed_updates": json.dumps(["message"])})
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/getUpdates?{params}")
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
        return resp.read()


def parse_updates(raw: bytes) -> Tuple[List[InboundMessage], List[int]]:
    """Returns (text messages, update_ids that carried NO usable text — photos, voice notes,
    stickers, captions-only media, etc.). Non-text updates must be surfaced, not vanished:
    a swallowed message looks to the owner like a dead bot."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [], []
    out: List[InboundMessage] = []
    textless: List[int] = []
    for u in data.get("result", []):
        uid = u.get("update_id")
        if not isinstance(uid, int):
            continue
        msg = u.get("message") or {}
        text = (msg.get("text") or msg.get("caption") or "").strip()
        chat = str((msg.get("chat") or {}).get("id", ""))
        if text and chat:
            out.append(InboundMessage(update_id=uid, chat_id=chat, text=text))
        else:
            textless.append(uid)
    return out, textless


def poll(token: str, owner_chat_id: str, offset: int,
         fetcher: Callable[[str, int], bytes] = default_fetcher) -> Tuple[int, List[str], int]:
    """Fetch new messages. Returns (next_offset, texts_from_owner, n_unreadable).
    Foreign-chat messages advance the offset (consumed) but are never returned or answered."""
    try:
        updates, textless = parse_updates(fetcher(token, offset))
    except Exception:
        return offset, [], 0                               # network failure: try next tick
    next_offset = offset
    texts: List[str] = []
    for uid in textless:
        next_offset = max(next_offset, uid + 1)
    for m in updates:
        next_offset = max(next_offset, m.update_id + 1)
        if m.chat_id == str(owner_chat_id):
            texts.append(m.text)
    return next_offset, texts, len(textless)


def classify(text: str) -> str:
    """'command:<name>' for known commands (with or without /), else 'question'."""
    t = text.strip().lstrip("/").lower()
    return f"command:{t}" if t in COMMANDS else "question"
