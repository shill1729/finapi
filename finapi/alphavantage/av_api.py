from __future__ import annotations

import logging
from typing import List, Optional, Union

import pandas as pd

from ..utils.error_handling import RequestRetryHandler
from ..utils.rate_limiting import RateLimiter
from ..utils.time_handling import Interval, Period

logger = logging.getLogger(__name__)

# Alpha Vantage API response keys that signal a rate-limit or info message
# rather than actual data.
_AV_SOFT_ERROR_KEYS = {"Information", "Note", "Error Message"}


class AlphaVantageAPI:
    """
    Wraps the Alpha Vantage API for historical price data and options chains.

    Supports equities and a curated set of cryptocurrencies. All requests
    are automatically rate-limited and retried on transient failures.

    Args:
        api_key: Alpha Vantage API key.
        calls_per_minute: Rate limit enforced between requests. Default matches
            the standard paid plan (75/min). Lower this if you hit 429s.
    """

    # TODO: separate equity and crypto into distinct subclasses.
    BASE_URL = "https://www.alphavantage.co/query"
    COIN_NAMES: List[str] = [
        "BTC", "ETH", "DOGE", "AVAX", "SHIB", "LINK",
        "BCH", "LTC", "ETC", "AAVE", "BONK", "PEPE", "TRUMP",
        "SOL", "DOT", "PENGU", "XRP",
    ]

    def __init__(self, api_key: str, calls_per_minute: float = 75.0):
        self.api_key = api_key
        self._retry_handler = RequestRetryHandler()
        self._rate_limiter = RateLimiter(calls_per_minute=calls_per_minute)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_request(self, params: dict) -> dict:
        """Rate-limit, then GET with automatic retry. Raises on AV soft errors."""
        clean_params = {k: v for k, v in params.items() if v is not None}
        clean_params["apikey"] = self.api_key

        self._rate_limiter.wait()
        response = self._retry_handler.request_with_retry(
            "GET", self.BASE_URL, params=clean_params, timeout=30
        )
        response.raise_for_status()
        data = response.json()

        for key in _AV_SOFT_ERROR_KEYS:
            if key in data:
                raise RuntimeError(f"Alpha Vantage API message ({key}): {data[key]}")
        return data

    @staticmethod
    def _get_function_name(is_crypto: bool, period: Period, adjusted: bool) -> str:
        if is_crypto:
            prefix = "CRYPTO" if period == Period.INTRADAY else "DIGITAL_CURRENCY"
            return f"{prefix}_{period.value.upper()}"
        base = "TIME_SERIES"
        if period != Period.INTRADAY and adjusted:
            return f"{base}_{period.value.upper()}_ADJUSTED"
        return f"{base}_{period.value.upper()}"

    @staticmethod
    def _parse_time_series(data: dict, period: Period, is_crypto: bool, adjusted: bool) -> pd.Series:
        """Extract the closing-price Series from a raw AV time-series response."""
        ts_keys = [k for k in data if "Time Series" in k]
        if not ts_keys:
            raise KeyError(
                f"No time series key found in response. Keys present: {list(data.keys())}"
            )

        df = pd.DataFrame.from_dict(data[ts_keys[0]], orient="index").astype(float)
        df.index = pd.to_datetime(df.index)

        # Column naming:
        # - CRYPTO_* (all periods) → '4. close'   (AV unified the format)
        # - TIME_SERIES_*          → '4. close' or '5. adjusted close'
        if is_crypto:
            price_col = "4. close"
        else:
            price_col = "5. adjusted close" if adjusted and period != Period.INTRADAY else "4. close"

        if price_col not in df.columns:
            raise KeyError(
                f"Expected column {price_col!r} not found. "
                f"Available columns: {list(df.columns)}"
            )

        return df[price_col].sort_index()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_historical_data(
        self,
        symbol: str,
        period: Period = Period.DAILY,
        interval: Optional[Interval] = None,
        adjusted: bool = True,
    ) -> pd.Series:
        """
        Retrieve closing prices for a single symbol.

        Args:
            symbol: Ticker (e.g. 'AAPL') or coin name (e.g. 'BTC').
            period: Data granularity.
            interval: Required when period is INTRADAY.
            adjusted: Use adjusted close for equities. Ignored for crypto.

        Returns:
            pd.Series of float closing prices, indexed by date (ascending).
        """
        is_crypto = symbol in self.COIN_NAMES
        params: dict = {
            "function": self._get_function_name(is_crypto, period, adjusted),
            "symbol": symbol,
            "market": "USD" if is_crypto else None,
            "outputsize": "full",
        }

        if period == Period.INTRADAY:
            if not interval:
                raise ValueError("interval must be specified for Period.INTRADAY")
            params["interval"] = interval.value

        if not is_crypto and period != Period.INTRADAY:
            params["adjusted"] = "true" if adjusted else "false"

        return self._parse_time_series(self._make_request(params), period, is_crypto, adjusted)

    def get_assets(
        self,
        symbols: Union[str, List[str]],
        period: Period = Period.DAILY,
        interval: Optional[Interval] = None,
        adjusted: bool = True,
    ) -> pd.DataFrame:
        """
        Retrieve closing prices for one or more symbols as a DataFrame.

        Requests are issued sequentially with rate limiting applied between
        each one. For large batches, expect roughly 60/calls_per_minute seconds
        per symbol.

        Args:
            symbols: A single ticker/coin or a list of them.
            period: Data granularity.
            interval: Required when period is INTRADAY.
            adjusted: Use adjusted close for equities.

        Returns:
            pd.DataFrame — columns are symbols, index is date. Rows with any
            NaN are dropped so all columns share the same date range.
        """
        if isinstance(symbols, str):
            symbols = [symbols]
        if not symbols:
            raise ValueError("symbols must not be empty")

        series_list = []
        for i, symbol in enumerate(symbols, 1):
            logger.info("Fetching %s (%d/%d)", symbol, i, len(symbols))
            series_list.append(self.get_historical_data(symbol, period, interval, adjusted))

        result = pd.concat(series_list, axis=1)
        result.columns = symbols
        return result.dropna()

    def get_options_chain(
        self,
        symbol: str,
        expiration: Optional[Union[str, pd.Timestamp]] = None,
        option_type: Optional[str] = None,
        session_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Retrieve the historical options chain for a given underlying.

        Args:
            symbol: Underlying ticker, e.g. 'SPY'.
            expiration: Filter to a specific expiration (YYYY-MM-DD or Timestamp).
            option_type: Filter by 'call' or 'put' (case-insensitive).
            session_date: Session date (YYYY-MM-DD); must be >= 2008-01-01.

        Returns:
            pd.DataFrame with typed columns (greeks as float, sizes as Int64).
            Returns an empty DataFrame with expected columns if no data found.
        """
        params: dict = {"function": "HISTORICAL_OPTIONS", "symbol": symbol.upper()}
        if session_date is not None:
            if pd.to_datetime(session_date) < pd.Timestamp("2008-01-01"):
                raise ValueError("session_date must be on or after 2008-01-01 (AV data cutoff).")
            params["date"] = session_date

        records = self._make_request(params).get("data", [])
        if not records:
            return pd.DataFrame(columns=[
                "contractID", "symbol", "expiration", "strike", "type", "last", "mark",
                "bid", "bid_size", "ask", "ask_size", "volume", "open_interest", "date",
                "implied_volatility", "delta", "gamma", "theta", "vega", "rho",
            ])

        df = pd.DataFrame.from_records(records)

        for col in ("expiration", "date"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")

        float_cols = ["strike", "last", "mark", "bid", "ask", "implied_volatility",
                      "delta", "gamma", "theta", "vega", "rho"]
        int_cols = ["bid_size", "ask_size", "volume", "open_interest"]
        for c in float_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        for c in int_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")

        if option_type is not None:
            opt = option_type.strip().lower()
            if opt not in {"call", "put"}:
                raise ValueError("option_type must be 'call' or 'put'")
            if "type" in df.columns:
                df = df[df["type"].str.lower() == opt]

        if expiration is not None and "expiration" in df.columns:
            df = df[df["expiration"] == pd.to_datetime(expiration, errors="coerce")]

        sort_cols = [c for c in ("expiration", "type", "strike", "date", "contractID") if c in df.columns]
        return df.sort_values(sort_cols).reset_index(drop=True) if sort_cols else df
