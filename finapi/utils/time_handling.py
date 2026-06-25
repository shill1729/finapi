from __future__ import annotations

from enum import Enum

import pandas as pd


class Period(Enum):
    INTRADAY = "intraday"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class Interval(Enum):
    ONE_MIN = "1min"
    FIVE_MIN = "5min"
    FIFTEEN_MIN = "15min"
    THIRTY_MIN = "30min"
    SIXTY_MIN = "60min"


# Minutes per bar for each Interval member.
_INTERVAL_MINUTES: dict[Interval, int] = {
    Interval.ONE_MIN: 1,
    Interval.FIVE_MIN: 5,
    Interval.FIFTEEN_MIN: 15,
    Interval.THIRTY_MIN: 30,
    Interval.SIXTY_MIN: 60,
}


def compute_time_step(
    period: Period,
    interval: Interval | None = None,
    asset_class: str = "equity",
) -> float:
    """
    Returns the fraction of a year represented by one data point.

    Used for annualizing volatility: annualized_vol = period_vol / sqrt(dt).

    Args:
        period: Data granularity.
        interval: Required when period is INTRADAY.
        asset_class: 'equity' (252-day, 6.5h sessions) or 'crypto' (365-day, 24h).

    Returns:
        dt in years (e.g. 1/252 for daily equity, 1/98280 for 1-min equity).
    """
    if asset_class == "equity":
        intraday_hours = 6.5
        trading_days_per_week = 5
        days_per_year = 252
    elif asset_class == "crypto":
        intraday_hours = 24.0
        trading_days_per_week = 7
        days_per_year = 365
    else:
        raise ValueError(f"asset_class must be 'equity' or 'crypto', got {asset_class!r}")

    if period == Period.INTRADAY:
        if interval is None:
            raise ValueError("interval must be specified for Period.INTRADAY")
        minutes_per_bar = _INTERVAL_MINUTES[interval]
        minutes_per_year = intraday_hours * 60 * days_per_year
        return minutes_per_bar / minutes_per_year

    return {
        Period.DAILY: 1.0 / days_per_year,
        Period.WEEKLY: float(trading_days_per_week) / days_per_year,
        Period.MONTHLY: 1.0 / 12,
    }[period]


def is_us_equity_market_open(now_utc: pd.Timestamp | None = None) -> bool:
    """
    Returns True if the given moment falls within regular US equity trading hours
    (Mon–Fri, 09:30–16:00 ET).

    Args:
        now_utc: Timestamp to check. Tz-naive is assumed UTC. Defaults to now.
    """
    if now_utc is None:
        now_utc = pd.Timestamp.now("UTC")
    elif now_utc.tz is None:
        now_utc = now_utc.tz_localize("UTC")
    else:
        now_utc = now_utc.tz_convert("UTC")

    now_et = now_utc.tz_convert("America/New_York")

    if now_et.weekday() > 4:  # Saturday=5, Sunday=6
        return False

    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now_et <= market_close
