"""News ingestion: RSS/Atom feeds (market news + SEC EDGAR) via feedparser.

Everything ingested is UNTRUSTED TEXT. It is stored verbatim, scored by deterministic rules
(news/scoring.py) and — at most — shown to the model inside the sandbox bundle. Nothing here
or downstream ever executes, follows instructions from, or trades directly on this text; the
worst prompt injection can do is nudge the model to rotate among whitelisted instruments.

Feeds are plain URLs; the defaults cover broad market wires plus the EDGAR current-events
feed for 8-K filings. Fetching is injectable so tests run on fixture bytes, offline.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set

import feedparser

USER_AGENT = "ibagent/0.1 (personal portfolio engine; contact via repo)"
FETCH_TIMEOUT_S = 20
MAX_ITEMS_PER_FEED = 60
MAX_TEXT_CHARS = 800

DEFAULT_FEEDS: List[str] = [
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",          # MarketWatch top
    "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",         # MarketWatch pulse
    "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",   # MarketWatch real-time
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",               # CNBC top news
    "https://www.cnbc.com/id/15839135/device/rss/rss.html",                # CNBC markets
    "https://www.cnbc.com/id/19854910/device/rss/rss.html",                # CNBC earnings
    "https://www.cnbc.com/id/100727362/device/rss/rss.html",               # CNBC technology
    "https://finance.yahoo.com/news/rssindex",                             # Yahoo Finance
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=8-K&dateb=&owner=include"
    "&count=40&output=atom",                                               # EDGAR current 8-Ks
]


@dataclass(frozen=True)
class NewsItem:
    id: str                      # stable hash of link|title
    source: str                  # feed URL
    title: str
    summary: str
    link: str
    published: str               # ISO UTC ("" if the feed gave none)
    fetched: str                 # ISO UTC


def _clean(text: str) -> str:
    return " ".join((text or "").split())[:MAX_TEXT_CHARS]


def item_id(link: str, title: str) -> str:
    return hashlib.sha256(f"{link}|{title}".encode("utf-8", "replace")).hexdigest()[:24]


def _entry_time(entry) -> str:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                # feedparser normalizes to a UTC struct_time -> timegm, NOT mktime (local time)
                return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc).isoformat(timespec="seconds")
            except (OverflowError, ValueError):
                continue
    return ""


def default_fetcher(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
        return resp.read()


def parse_feed(source_url: str, content: bytes, now: Optional[datetime] = None) -> List[NewsItem]:
    fetched = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    parsed = feedparser.parse(content)
    out: List[NewsItem] = []
    for entry in parsed.entries[:MAX_ITEMS_PER_FEED]:
        title = _clean(getattr(entry, "title", ""))
        link = _clean(getattr(entry, "link", ""))
        if not title or not link:
            continue
        out.append(NewsItem(id=item_id(link, title), source=source_url, title=title,
                            summary=_clean(getattr(entry, "summary", "")), link=link,
                            published=_entry_time(entry), fetched=fetched))
    return out


def poll(feeds: Iterable[str], seen: Set[str], fetcher: Optional[Callable[[str], bytes]] = None,
         now: Optional[datetime] = None) -> List[NewsItem]:
    """Fetch all feeds, return NEW items only (not in `seen`). A dead feed is skipped, never fatal."""
    fetch = fetcher or default_fetcher
    fresh: List[NewsItem] = []
    for url in feeds:
        try:
            content = fetch(url)
        except Exception:
            continue                                      # network/feed failure: degrade, don't die
        for item in parse_feed(url, content, now):
            if item.id not in seen:
                seen.add(item.id)
                fresh.append(item)
    return fresh


class NewsStore:
    """Persists seen ids + a rolling window of recent items (data/news_state.json)."""

    def __init__(self, path: Path | str, keep_items: int = 400, keep_ids: int = 5000):
        self.path = Path(path)
        self.keep_items, self.keep_ids = keep_items, keep_ids
        self.seen: Set[str] = set()
        self.items: List[NewsItem] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.seen = set(data.get("seen", []))
            self.items = [NewsItem(**d) for d in data.get("items", [])]
        except (json.JSONDecodeError, TypeError, OSError):
            self.seen, self.items = set(), []              # corrupt state: start clean (ids re-dedupe)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"seen": sorted(self.seen)[-self.keep_ids:],
                "items": [asdict(i) for i in self.items[-self.keep_items:]]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, items: List[NewsItem]) -> None:
        self.items.extend(items)
        self.items = self.items[-self.keep_items:]

    def recent(self, hours: float, now: Optional[datetime] = None) -> List[NewsItem]:
        now = now or datetime.now(timezone.utc)
        cutoff = now.timestamp() - hours * 3600
        out = []
        for i in self.items:
            ts = i.published or i.fetched
            try:
                if datetime.fromisoformat(ts).timestamp() >= cutoff:
                    out.append(i)
            except ValueError:
                continue
        return out
