import copy
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

# A Wednesday, 11:00 ET (15:00 UTC in August/EDT): regular NYSE session, outside the
# open/close no-trade buffers. Used by risk/sleeve tests that need a live-market clock.
NOW = datetime(2026, 8, 12, 15, 0, tzinfo=timezone.utc)
TODAY = NOW.date()


@pytest.fixture(scope="session")
def mandate_dict():
    with (ROOT / "mandate.yaml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture
def md(mandate_dict):
    """Fresh deep copy per test, with the capital knobs PINNED to the values the tests were
    written against — user tuning of mandate.yaml (e.g. fixed-pricing floors) must not move
    the goalposts of the engine tests."""
    d = copy.deepcopy(mandate_dict)
    d["capital"]["commission_model"] = "tiered"
    d["capital"]["min_position_usd"] = 100
    d["account"]["ibkr_account_id"] = ""
    d["broker"]["fractional_shares"] = True
    d["risk"]["max_position_weight_pct"] = {"core": 0.35, "trend": 0.12, "spec": 0.06}
    d["risk"]["max_new_positions_per_week"] = 3
    d["execution"]["limit_offset_bps"] = 15
    d["llm"]["max_turns"] = {"weekly": 25, "daily": 8, "event": 8}
    d["llm"]["timeout_seconds"] = {"weekly": 900, "daily": 420, "event": 420}
    d["llm"]["daily_invocation_cap"] = 4
    # never let tests reach the real Telegram API (the supervisor polls it when configured)
    d["alerts"]["channels"] = ["stdout"]
    return d


@pytest.fixture
def mandate(md):
    from ibagent.config import mandate_from_dict
    return mandate_from_dict(md)


def make_quote(symbol: str, price: float, spread_bps: float = 4.0, ts: datetime = NOW):
    from ibagent.broker.base import Quote
    half = price * spread_bps / 20_000.0
    return Quote(symbol=symbol, bid=round(price - half, 4), ask=round(price + half, 4),
                 last=price, ts=ts, delayed=True)


def make_book(tmp_path, cash: float = 1000.0):
    from ibagent.book import Book
    book = Book(tmp_path / "book.json")
    book.apply_contribution(cash)
    book.ensure_week(TODAY)
    book.ensure_day(TODAY, cash)
    return book
