from datetime import datetime, timedelta, timezone

from ibagent.config import EventCfg
from ibagent.news.ingest import NewsItem, NewsStore, parse_feed, poll
from ibagent.news.scoring import (EventGateState, build_digest, check_event_gate, score_items)

NOW = datetime(2026, 8, 12, 15, 0, tzinfo=timezone.utc)

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Test feed</title>
<item><title>Apple beats estimates, raises guidance</title>
  <link>https://x.test/apple-q3</link>
  <description>AAPL quarterly results top expectations</description>
  <pubDate>Wed, 12 Aug 2026 13:00:00 GMT</pubDate></item>
<item><title>Fed holds rates, signals September cut</title>
  <link>https://x.test/fomc</link><description>FOMC decision</description>
  <pubDate>Wed, 12 Aug 2026 14:00:00 GMT</pubDate></item>
<item><title>Quiet day in markets</title>
  <link>https://x.test/quiet</link><description>Nothing much happened</description>
  <pubDate>Wed, 12 Aug 2026 12:00:00 GMT</pubDate></item>
</channel></rss>"""


def items():
    return parse_feed("https://feed.test/rss", RSS, NOW)


def test_parse_feed_and_dedupe(tmp_path):
    got = items()
    assert len(got) == 3 and got[0].title.startswith("Apple")
    seen = set()
    first = poll(["u"], seen, fetcher=lambda u: RSS, now=NOW)
    again = poll(["u"], seen, fetcher=lambda u: RSS, now=NOW)
    assert len(first) == 3 and again == []
    store = NewsStore(tmp_path / "news.json")
    store.seen = seen
    store.add(first)
    store.save()
    store2 = NewsStore(tmp_path / "news.json")
    assert len(store2.items) == 3 and store2.seen == seen
    assert len(store2.recent(4, NOW)) == 3
    assert len(store2.recent(2.5, NOW)) == 2               # the 12:00 item ages out
    assert len(store2.recent(0.5, NOW)) == 0


def test_dead_feed_is_skipped():
    def fetcher(url):
        raise OSError("down")
    assert poll(["u"], set(), fetcher=fetcher, now=NOW) == []


def test_scoring_tags_symbols_and_weights():
    scored = score_items(items(), ["AAPL", "MSFT"])
    apple = next(s for s in scored if "apple-q3" in s.item.link)
    assert "AAPL" in apple.symbols and apple.score >= 0.7   # earnings + guidance keywords
    fomc = next(s for s in scored if "fomc" in s.item.link)
    assert fomc.symbols == () and 0 < fomc.score < apple.score
    quiet = next(s for s in scored if "quiet" in s.item.link)
    assert quiet.score == 0.0


def test_preview_and_commentary_titles_are_dampened_below_the_gate():
    """2026-09-02: 'Cramer Says Nvidia at 23 Times Earnings Needs a Half Trillion Dollar
    Buyback' scored 0.8 (buyback + earnings keywords) and 'What to watch in Broadcom's
    upcoming earnings' scored 0.7 — together 14 event runs fleet-wide, every one no_change
    (fleet lesson 9: previews are not events). Halved scores stay in the digest but under
    the gate's 0.70."""
    def mk(title, link):
        return NewsItem(id=link, source="s", title=title, link=link, summary="",
                        published=NOW.isoformat(), fetched=NOW.isoformat())
    previews = [
        mk("Cramer Says Nvidia at 23 Times Earnings Needs a Half Trillion Dollar Buyback", "l1"),
        mk("What to watch in Broadcom’s upcoming earnings – and why Nvidia is running", "l2"),
        mk("Nvidia earnings preview: what Wall Street expects", "l3"),
        mk("Home Depot faces a critical test on Wednesday with quarterly results due", "l4"),
    ]
    scored = score_items(previews, ["NVDA", "AVGO", "HD"])
    for s in scored:
        assert 0.3 <= s.score < 0.7, s.item.title          # digest yes, event gate no
        assert "preview/commentary: halved" in s.reasons
    # a real print is untouched
    real = score_items([mk("Nvidia beats estimates, raises guidance on record data center revenue",
                           "l5")], ["NVDA"])[0]
    assert real.score >= 0.7 and "preview/commentary: halved" not in real.reasons
    # and the gate does not fire on a dampened headline even with a big move
    st = EventGateState()
    assert check_event_gate(gate_cfg(), st, scored, {"NVDA"}, set(), {"NVDA": 0.04}, NOW) is None
    assert st.count_today == 0


def test_digest_sections():
    scored = score_items(items(), ["AAPL"])
    md = build_digest(scored, held={"AAPL"}, watched=set())
    assert "UNTRUSTED" in md and "Held / watched" in md and "Macro" in md
    assert "Apple beats" in md and "Quiet day" not in md


def gate_cfg(**kw):
    base = dict(max_per_day=2, cooldown_minutes=120, min_materiality=0.7, min_abs_move_pct=0.03)
    base.update(kw)
    return EventCfg(**base)


def test_event_gate_fires_and_respects_budget():
    scored = score_items(items(), ["AAPL"])
    state = EventGateState()
    t = check_event_gate(gate_cfg(), state, scored, {"AAPL"}, set(), {"AAPL": -0.05}, NOW)
    assert t is not None and t.symbol == "AAPL" and state.count_today == 1
    # cooldown blocks an immediate second fire
    assert check_event_gate(gate_cfg(), state, scored, {"AAPL"}, set(), {"AAPL": -0.05}, NOW) is None
    # after cooldown, a NEW headline gets the second slot, then the budget is exhausted
    fresh = score_items([NewsItem(id="n2", source="s", title="Apple guidance cut, earnings miss",
                                  link="https://x.test/apple-2", summary="AAPL",
                                  published=NOW.isoformat(), fetched=NOW.isoformat())], ["AAPL"])
    later = NOW + timedelta(hours=3)
    assert check_event_gate(gate_cfg(), state, fresh, {"AAPL"}, set(), {"AAPL": -0.05}, later)
    even_later = NOW + timedelta(hours=7)
    assert check_event_gate(gate_cfg(), state, scored + fresh, {"AAPL"}, set(), {"AAPL": -0.05},
                            even_later) is None
    # new day resets the counter (and the per-headline memory)
    tomorrow = NOW + timedelta(days=1)
    assert check_event_gate(gate_cfg(), state, scored, {"AAPL"}, set(), {"AAPL": -0.05}, tomorrow)


def test_event_gate_outside_rth_spends_nothing():
    """2026-08-27: pre-market NVDA headlines consumed the whole daily event budget on
    main/swing/sniper before the open; the session then had no event run left."""
    scored = score_items(items(), ["AAPL"])
    st = EventGateState()
    for _ in range(5):        # pre-market polls: material news + a big move, but no run possible
        assert check_event_gate(gate_cfg(), st, scored, {"AAPL"}, set(), {"AAPL": -0.05}, NOW,
                                can_fire=False) is None
    assert st.count_today == 0 and st.last_trigger_ts == 0.0
    # first in-RTH poll fires with the full budget intact
    t = check_event_gate(gate_cfg(), st, scored, {"AAPL"}, set(), {"AAPL": -0.05}, NOW)
    assert t is not None and st.count_today == 1


def test_event_gate_fires_each_headline_once_per_day():
    """2026-08-28: one CRM headline re-fired every cooldown on all 7 variants (24 runs
    fleet-wide), each answering 'same headline, same answer'."""
    scored = score_items(items(), ["AAPL"])
    st = EventGateState()
    assert check_event_gate(gate_cfg(), st, scored, {"AAPL"}, set(), {"AAPL": -0.05}, NOW)
    later = NOW + timedelta(hours=3)                      # cooldown over, budget left
    assert check_event_gate(gate_cfg(), st, scored, {"AAPL"}, set(), {"AAPL": -0.05}, later) is None
    assert st.count_today == 1                            # nothing spent on the repeat
    # the dedupe survives a state round-trip and resets with the day
    st2 = EventGateState.from_dict(st.as_dict())
    assert check_event_gate(gate_cfg(), st2, scored, {"AAPL"}, set(), {"AAPL": -0.05}, later) is None
    assert check_event_gate(gate_cfg(), st2, scored, {"AAPL"}, set(), {"AAPL": -0.05},
                            NOW + timedelta(days=1))


def test_event_gate_requires_move_and_holding():
    scored = score_items(items(), ["AAPL"])
    st = EventGateState()
    assert check_event_gate(gate_cfg(), st, scored, {"AAPL"}, set(), {"AAPL": -0.01}, NOW) is None
    assert check_event_gate(gate_cfg(), st, scored, {"MSFT"}, set(), {"AAPL": -0.05}, NOW) is None
    # watched (not held) symbols count
    assert check_event_gate(gate_cfg(), st, scored, set(), {"AAPL"}, {"AAPL": 0.05}, NOW)
