"""Secrets and alerts.

Secrets resolve from environment first, then the OS credential store via `keyring`
(Windows Credential Manager). Store with:  ibagent secret set TELEGRAM_BOT_TOKEN
Never put secrets in the repo, the mandate, or anywhere under the LLM runs root.

Alerts fan out to configured sinks; sending never raises into the engine.
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Dict, List, Literal, Optional, Protocol

from ibagent.config import AlertsCfg

log = logging.getLogger(__name__)
KEYRING_SERVICE = "ibagent"
Level = Literal["info", "warning", "critical"]


# ----------------------------------------------------------------------------- secrets


def _sanitize(val: Optional[str]) -> Optional[str]:
    """Strip whitespace and control characters (getpass on Windows can capture backspaces as
    \\x7f); a secret is never legitimately made of control bytes."""
    if val is None:
        return None
    cleaned = "".join(c for c in val if c.isprintable()).strip()
    return cleaned or None


def get_secret(name: str) -> Optional[str]:
    val = _sanitize(os.environ.get(name))
    if val:
        return val
    try:
        import keyring  # optional at import time; required if you use the credential store
        return _sanitize(keyring.get_password(KEYRING_SERVICE, name))
    except Exception:  # keyring missing or backend unavailable
        return None


def set_secret(name: str, value: str) -> None:
    import keyring
    keyring.set_password(KEYRING_SERVICE, name, value)


def require_secret(name: str) -> str:
    val = get_secret(name)
    if not val:
        raise RuntimeError(f"missing secret {name} (env var or keyring service '{KEYRING_SERVICE}')")
    return val


# ----------------------------------------------------------------------------- alerts


_LEVEL_EMOJI = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass(frozen=True)
class Alert:
    level: Level
    title: str
    body: str = ""
    ts: float = field(default_factory=time.time)

    def text(self) -> str:
        tag = _LEVEL_EMOJI[self.level]
        return f"{tag} [{self.level.upper()}] {self.title}\n{self.body}".strip()

    def html(self) -> str:
        """Telegram HTML: bold title; multi-line bodies (tables/reports) go monospace so
        columns line up on a phone."""
        head = f"<b>{_LEVEL_EMOJI[self.level]} {_html_escape(self.title)}</b>"
        if not self.body:
            return head
        body = _html_escape(self.body.strip())
        return f"{head}\n<pre>{body}</pre>" if "\n" in self.body else f"{head}\n{body}"


class AlertSink(Protocol):
    def send(self, alert: Alert) -> None: ...


class StdoutSink:
    def send(self, alert: Alert) -> None:
        print(alert.text(), flush=True)


class TelegramSink:
    def __init__(self, token: str, chat_id: str, timeout_s: float = 10.0):
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._chat_id, self._timeout = chat_id, timeout_s

    def send(self, alert: Alert) -> None:
        data = urllib.parse.urlencode({"chat_id": self._chat_id, "parse_mode": "HTML",
                                       "text": alert.html()[:4000]}).encode()
        req = urllib.request.Request(self._url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            if resp.status != 200:
                raise RuntimeError(f"telegram HTTP {resp.status}")


class EmailSink:
    def __init__(self, host: str, port: int, user: str, password: str, to_addr: str, from_addr: Optional[str] = None):
        self._host, self._port, self._user, self._password = host, port, user, password
        self._to, self._from = to_addr, from_addr or user

    def send(self, alert: Alert) -> None:
        msg = EmailMessage()
        msg["Subject"] = f"[ibagent {alert.level}] {alert.title}"[:200]
        msg["From"], msg["To"] = self._from, self._to
        msg.set_content(alert.text())
        with smtplib.SMTP(self._host, self._port, timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(self._user, self._password)
            smtp.send_message(msg)


class WindowsToastSink:
    def send(self, alert: Alert) -> None:
        from winotify import Notification  # optional dependency (pip install ibagent[windows])
        Notification(app_id="ibagent", title=f"[{alert.level}] {alert.title}", msg=alert.body[:200]).show()


class Alerter:
    """Fan-out with dedupe: identical non-critical (level,title) within `dedupe_s` is suppressed."""

    def __init__(self, sinks: List[AlertSink], dedupe_s: float = 1800.0):
        self._sinks, self._dedupe_s = list(sinks), dedupe_s
        self._last: Dict[tuple, float] = {}
        self.failures = 0

    def send(self, level: Level, title: str, body: str = "") -> bool:
        alert = Alert(level=level, title=title, body=body)
        key = (level, title)
        if level != "critical" and time.time() - self._last.get(key, 0.0) < self._dedupe_s:
            return False
        self._last[key] = time.time()
        delivered = False
        for sink in self._sinks:
            try:
                sink.send(alert)
                delivered = True
            except Exception as exc:  # never let alerting take the engine down
                self.failures += 1
                log.error("alert sink %s failed: %s", type(sink).__name__, exc)
        return delivered

    def info(self, title: str, body: str = "") -> bool: return self.send("info", title, body)
    def warning(self, title: str, body: str = "") -> bool: return self.send("warning", title, body)
    def critical(self, title: str, body: str = "") -> bool: return self.send("critical", title, body)


def build_alerter(cfg: AlertsCfg) -> Alerter:
    sinks: List[AlertSink] = []
    for ch in cfg.channels:
        if ch == "stdout":
            sinks.append(StdoutSink())
        elif ch == "telegram":
            sinks.append(TelegramSink(require_secret("TELEGRAM_BOT_TOKEN"), require_secret("TELEGRAM_CHAT_ID")))
        elif ch == "email":
            sinks.append(EmailSink(require_secret("SMTP_HOST"), int(require_secret("SMTP_PORT")),
                                   require_secret("SMTP_USER"), require_secret("SMTP_PASSWORD"),
                                   require_secret("ALERT_EMAIL_TO")))
        elif ch == "windows_toast":
            sinks.append(WindowsToastSink())
    return Alerter(sinks, dedupe_s=cfg.dedupe_minutes * 60.0)
