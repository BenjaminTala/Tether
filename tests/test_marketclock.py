from datetime import date, datetime, timezone

from ibagent.marketclock import (add_trading_days, easter_sunday, in_no_trade_window, is_early_close,
                                 is_rth, is_trading_day, next_trading_day, nyse_holidays,
                                 previous_trading_day, session, trading_days_between)


def test_known_holidays_2026():
    h = nyse_holidays(2026)
    assert date(2026, 1, 1) in h                    # New Year's Day (Thu)
    assert date(2026, 1, 19) in h                   # MLK: 3rd Mon Jan
    assert date(2026, 2, 16) in h                   # Washington's Birthday
    assert date(2026, 4, 3) in h                    # Good Friday (Easter 2026-04-05)
    assert date(2026, 5, 25) in h                   # Memorial Day (last Mon May)
    assert date(2026, 6, 19) in h                   # Juneteenth (Fri)
    assert date(2026, 7, 3) in h                    # July 4 is a Saturday -> observed Friday
    assert date(2026, 9, 7) in h                    # Labor Day
    assert date(2026, 11, 26) in h                  # Thanksgiving
    assert date(2026, 12, 25) in h                  # Christmas (Fri)
    assert date(2026, 7, 4) not in h


def test_easter():
    assert easter_sunday(2026) == date(2026, 4, 5)
    assert easter_sunday(2025) == date(2025, 4, 20)
    assert easter_sunday(2024) == date(2024, 3, 31)


def test_sunday_holiday_observed_monday():
    # July 4 2027 is a Sunday -> observed Monday July 5
    assert date(2027, 7, 5) in nyse_holidays(2027)


def test_saturday_new_year_not_observed_prior_year():
    # Jan 1 2028 is a Saturday; NYSE does NOT close Dec 31 2027
    assert date(2028, 1, 1) not in nyse_holidays(2028)
    assert is_trading_day(date(2027, 12, 31))


def test_juneteenth_only_from_2022():
    assert date(2021, 6, 18) not in nyse_holidays(2021)     # Jun 19 2021 was a Saturday anyway
    assert date(2023, 6, 19) in nyse_holidays(2023)


def test_early_closes():
    assert is_early_close(date(2025, 7, 3))                 # day before a Friday July 4
    assert not is_early_close(date(2026, 7, 3))             # that day IS the observed holiday
    assert is_early_close(date(2026, 11, 27))               # day after Thanksgiving
    assert is_early_close(date(2026, 12, 24))               # Christmas Eve (Thu)
    assert not is_early_close(date(2026, 8, 12))


def test_session_and_rth():
    sess = session(date(2026, 8, 12))
    assert sess is not None
    o, c = sess
    assert (o.hour, o.minute) == (9, 30) and (c.hour, c.minute) == (16, 0)
    assert session(date(2026, 7, 3)) is None
    # 11:00 ET on a trading day == 15:00 UTC in August
    assert is_rth(datetime(2026, 8, 12, 15, 0, tzinfo=timezone.utc))
    assert not is_rth(datetime(2026, 8, 12, 2, 0, tzinfo=timezone.utc))
    # early-close day: 13:30 ET is after the 13:00 close
    assert not is_rth(datetime(2026, 11, 27, 18, 30, tzinfo=timezone.utc))


def test_no_trade_window():
    # 9:40 ET is inside the first-15-minutes buffer
    assert in_no_trade_window(datetime(2026, 8, 12, 13, 40, tzinfo=timezone.utc), 15, 10)
    assert not in_no_trade_window(datetime(2026, 8, 12, 15, 0, tzinfo=timezone.utc), 15, 10)
    # 15:55 ET is inside the last-10-minutes buffer
    assert in_no_trade_window(datetime(2026, 8, 12, 19, 55, tzinfo=timezone.utc), 15, 10)


def test_trading_day_math_skips_holidays():
    # Fri 2026-07-02 is the last trading day before the observed July 4 weekend
    assert next_trading_day(date(2026, 7, 2)) == date(2026, 7, 6)
    assert previous_trading_day(date(2026, 7, 6)) == date(2026, 7, 2)
    assert add_trading_days(date(2026, 7, 2), 1) == date(2026, 7, 6)
    assert add_trading_days(date(2026, 7, 2), 0) == date(2026, 7, 2)
    assert trading_days_between(date(2026, 7, 1), date(2026, 7, 7)) == 3   # Jul 2, 6, 7
    assert trading_days_between(date(2026, 7, 7), date(2026, 7, 7)) == 0
