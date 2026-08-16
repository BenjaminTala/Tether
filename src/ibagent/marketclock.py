"""NYSE market calendar and session clock.

Holidays are computed from the exchange's rules (movable feasts included), not a hardcoded
year list, so the table never goes stale. Covers: New Year's Day, MLK Day, Washington's
Birthday, Good Friday, Memorial Day, Juneteenth (2022+), Independence Day, Labor Day,
Thanksgiving, Christmas. Weekend holidays observe Fri/Mon per NYSE practice (a Saturday
New Year's Day is NOT observed on Dec 31 of the prior year — rule 7.2 keeps it in-year).

Early closes (13:00 ET): July 3 when July 4 falls Tue-Sat*, the day after Thanksgiving,
and Christmas Eve when it is a weekday. (*July 3 itself must be a trading day.)

One-off closures (mourning days, disasters) cannot be predicted by rule; NEVER_TRADE_DATES
holds any that are announced. Being wrong about a surprise closure is safe: orders are DAY
+ RTH-only, so they simply don't execute.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Set, Tuple
from zoneinfo import ZoneInfo

NYSE_TZ = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)

# Announced one-off full closures (e.g. presidential mourning days). Add as announced.
NEVER_TRADE_DATES: Set[date] = set()


def easter_sunday(year: int) -> date:
    """Gregorian Easter (Anonymous/Meeus algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th (1-based) `weekday` (Mon=0) of a month."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(d: date) -> Optional[date]:
    """NYSE observation: Sat -> preceding Fri, Sun -> following Mon.
    Returns None for a Saturday holiday whose Friday falls in the previous year (not observed)."""
    if d.weekday() == 5:
        obs = d - timedelta(days=1)
        return obs if obs.year == d.year else None
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def nyse_holidays(year: int) -> Set[date]:
    """Full-day closures for a calendar year."""
    fixed = [date(year, 1, 1), date(year, 7, 4), date(year, 12, 25)]
    if year >= 2022:
        fixed.append(date(year, 6, 19))                      # Juneteenth
    days = {_observed(d) for d in fixed}
    days.discard(None)
    days |= {
        _nth_weekday(year, 1, 0, 3),                         # MLK Day
        _nth_weekday(year, 2, 0, 3),                         # Washington's Birthday
        easter_sunday(year) - timedelta(days=2),             # Good Friday
        _last_weekday(year, 5, 0),                           # Memorial Day
        _nth_weekday(year, 9, 0, 1),                         # Labor Day
        _nth_weekday(year, 11, 3, 4),                        # Thanksgiving
    }
    return days | {d for d in NEVER_TRADE_DATES if d.year == year}


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in nyse_holidays(d.year)


def is_early_close(d: date) -> bool:
    if not is_trading_day(d):
        return False
    if d.month == 7 and d.day == 3:
        return True
    if d.month == 12 and d.day == 24:
        return True
    thanksgiving = _nth_weekday(d.year, 11, 3, 4)
    return d == thanksgiving + timedelta(days=1)


def session(d: date) -> Optional[Tuple[datetime, datetime]]:
    """(open, close) as tz-aware ET datetimes, or None on a non-trading day."""
    if not is_trading_day(d):
        return None
    close = EARLY_CLOSE if is_early_close(d) else REGULAR_CLOSE
    return (datetime.combine(d, REGULAR_OPEN, tzinfo=NYSE_TZ),
            datetime.combine(d, close, tzinfo=NYSE_TZ))


def is_rth(dt: datetime) -> bool:
    """True while the regular session is open at `dt` (naive datetimes are assumed UTC)."""
    local = utc(dt).astimezone(NYSE_TZ)
    sess = session(local.date())
    return sess is not None and sess[0] <= local < sess[1]


def in_no_trade_window(dt: datetime, first_minutes: int, last_minutes: int) -> bool:
    """True if `dt` is outside RTH or inside the configured open/close buffers."""
    local = utc(dt).astimezone(NYSE_TZ)
    sess = session(local.date())
    if sess is None:
        return True
    start = sess[0] + timedelta(minutes=first_minutes)
    end = sess[1] - timedelta(minutes=last_minutes)
    return not (start <= local < end)


def next_trading_day(d: date) -> date:
    cur = d + timedelta(days=1)
    while not is_trading_day(cur):
        cur += timedelta(days=1)
    return cur


def previous_trading_day(d: date) -> date:
    cur = d - timedelta(days=1)
    while not is_trading_day(cur):
        cur -= timedelta(days=1)
    return cur


def add_trading_days(d: date, n: int) -> date:
    """`n` NYSE trading days after `d` (n=0 returns `d`)."""
    if n < 0:
        raise ValueError("n must be >= 0")
    cur = d
    for _ in range(n):
        cur = next_trading_day(cur)
    return cur


def trading_days_between(start: date, end: date) -> int:
    """Trading days strictly after `start` up to and including `end` (0 if end <= start)."""
    if end <= start:
        return 0
    count, cur = 0, start
    while cur < end:
        cur = next_trading_day(cur)
        if cur <= end:
            count += 1
    return count


# --------------------------------------------------------------------- business-day settlement
# Settlement uses trading days: T+1 skips weekends AND exchange holidays.

def is_business_day(d: date) -> bool:
    return is_trading_day(d)


def add_business_days(d: date, n: int) -> date:
    return add_trading_days(d, n)


def utc(dt: datetime) -> datetime:
    """Normalise to tz-aware UTC (naive datetimes are assumed UTC)."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
