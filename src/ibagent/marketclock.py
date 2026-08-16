"""Market clock helpers used by SimBroker settlement and (Phase 3) the RTH/turnover logic.

Weekend-aware only for now; Phase 3 adds the NYSE holiday table. Being wrong here is safe:
treating a holiday as a business day makes settlement look *earlier* only in the simulator,
while the live engine reads settled cash from IBKR.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def is_business_day(d: date) -> bool:
    return d.weekday() < 5


def add_business_days(d: date, n: int) -> date:
    if n < 0:
        raise ValueError("n must be >= 0")
    cur = d
    while n > 0:
        cur += timedelta(days=1)
        if is_business_day(cur):
            n -= 1
    return cur


def utc(dt: datetime) -> datetime:
    """Normalise to tz-aware UTC (naive datetimes are assumed UTC)."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
