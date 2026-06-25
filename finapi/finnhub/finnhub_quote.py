from __future__ import annotations

from typing import Optional

import pandas as pd
from finnhub import Client

from ..utils.rate_limiting import RateLimiter

# README: Finnhub basic plan = 150 calls/min. All plans cap at 30 calls/sec.
# Default to 150/min (2.5/sec) to stay within the basic-plan per-minute limit.
_DEFAULT_CALLS_PER_MINUTE = 150.0


def get_quote_from_finnhub(
    symbols: list,
    client: Client,
    rate_limiter: Optional[RateLimiter] = None,
) -> list:
    """
    Fetches the current mid price for each symbol via Finnhub.

    Args:
        symbols: List of ticker symbols (e.g. ['AAPL', 'MSFT']).
        client: Authenticated finnhub.Client instance.
        rate_limiter: Optional shared RateLimiter. If not provided, a new one
            is created with the basic-plan default (150 calls/min). Pass a
            custom limiter when calling this function repeatedly so the interval
            is enforced across calls.

    Returns:
        List of current closing prices in the same order as symbols.
    """
    if rate_limiter is None:
        rate_limiter = RateLimiter(calls_per_minute=_DEFAULT_CALLS_PER_MINUTE)

    quotes = []
    for symbol in symbols:
        rate_limiter.wait()
        quotes.append(client.quote(symbol)["c"])
    return quotes


def update_with_rt_quotes_from_finnhub(
    prices: pd.DataFrame,
    client: Client,
    rate_limiter: Optional[RateLimiter] = None,
) -> pd.DataFrame:
    """
    Appends or overwrites today's row in a prices DataFrame with real-time quotes.

    Args:
        prices: DataFrame with tickers as columns and dates as index.
        client: Authenticated finnhub.Client instance.
        rate_limiter: Optional shared RateLimiter (see get_quote_from_finnhub).

    Returns:
        Updated DataFrame with today's quotes added. Does not mutate the input
        when appending a new row; does mutate in-place when updating an existing one.
    """
    today = pd.Timestamp.now("UTC").normalize().tz_localize(None)
    symbols = list(prices.columns)
    quotes = get_quote_from_finnhub(symbols, client, rate_limiter)

    if today in prices.index:
        prices.loc[today] = quotes
        return prices

    new_row = pd.DataFrame([quotes], columns=symbols, index=[today])
    return pd.concat([prices, new_row])
