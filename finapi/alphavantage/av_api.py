from __future__ import annotations

import io
import logging
import re
from typing import Dict, Iterable, List, Optional, Union

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

    def _make_csv_request(self, params: dict) -> pd.DataFrame:
        """Rate-limit, then GET a CSV-format endpoint with automatic retry."""
        clean_params = {k: v for k, v in params.items() if v is not None}
        clean_params["apikey"] = self.api_key

        self._rate_limiter.wait()
        response = self._retry_handler.request_with_retry(
            "GET", self.BASE_URL, params=clean_params, timeout=30
        )
        response.raise_for_status()

        if "json" in response.headers.get("Content-Type", ""):
            data = response.json()
            for key in _AV_SOFT_ERROR_KEYS:
                if key in data:
                    raise RuntimeError(f"Alpha Vantage API message ({key}): {data[key]}")
            raise RuntimeError(f"Expected CSV response, got JSON: {data}")

        return pd.read_csv(io.StringIO(response.text))

    @staticmethod
    def _coerce_numeric_columns(df: pd.DataFrame, skip: Iterable[str] = ()) -> pd.DataFrame:
        """
        Convert AV's string-typed columns to numeric where it doesn't lose data.

        AV encodes every field as a string, including a literal "None" for
        missing values. A column is only converted if every value that isn't
        "None" parses as a number — this keeps genuine string columns (e.g.
        reportedCurrency, reportTime) untouched.
        """
        skip = set(skip)
        for col in df.columns:
            if col in skip:
                continue
            none_count = (df[col] == "None").sum()
            numeric = pd.to_numeric(df[col], errors="coerce")
            if numeric.isna().sum() == none_count:
                df[col] = numeric
        return df

    @classmethod
    def _records_to_frame(cls, records: List[dict], date_col: str) -> pd.DataFrame:
        """Build a date-indexed, numeric-coerced DataFrame from an AV records list."""
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame.from_records(records)
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = cls._coerce_numeric_columns(df, skip={date_col})
        return df.sort_values(date_col).set_index(date_col)

    def _get_financial_statement(self, function: str, symbol: str) -> Dict[str, pd.DataFrame]:
        data = self._make_request({"function": function, "symbol": symbol})
        return {
            "annual": self._records_to_frame(data.get("annualReports", []), "fiscalDateEnding"),
            "quarterly": self._records_to_frame(data.get("quarterlyReports", []), "fiscalDateEnding"),
        }

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
        month: Optional[str] = None,
    ) -> pd.Series:
        """
        Retrieve closing prices for a single symbol.

        Args:
            symbol: Ticker (e.g. 'AAPL') or coin name (e.g. 'BTC').
            period: Data granularity.
            interval: Required when period is INTRADAY.
            adjusted: Use adjusted close for equities. Ignored for crypto.
            month: Specific historical month to query (YYYY-MM), e.g. '2009-01'.
                Only valid for Period.INTRADAY equity requests; any month since
                2000-01 is supported. Implies outputsize=full for that month.

        Returns:
            pd.Series of float closing prices, indexed by date (ascending).
        """
        is_crypto = symbol in self.COIN_NAMES
        if month is not None:
            if period != Period.INTRADAY:
                raise ValueError("month is only valid when period is Period.INTRADAY")
            if is_crypto:
                raise ValueError("month is not supported for crypto intraday data")
            if not re.fullmatch(r"\d{4}-\d{2}", month):
                raise ValueError(f"month must be in YYYY-MM format, got {month!r}")

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
            params["month"] = month

        if not is_crypto and period != Period.INTRADAY:
            params["adjusted"] = "true" if adjusted else "false"

        return self._parse_time_series(self._make_request(params), period, is_crypto, adjusted)

    def get_assets(
        self,
        symbols: Union[str, List[str]],
        period: Period = Period.DAILY,
        interval: Optional[Interval] = None,
        adjusted: bool = True,
        month: Optional[str] = None,
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
            month: Specific historical month to query (YYYY-MM). Only valid
                for Period.INTRADAY equity requests.

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
            series_list.append(self.get_historical_data(symbol, period, interval, adjusted, month))

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

    # ------------------------------------------------------------------
    # Fundamental data
    # ------------------------------------------------------------------

    def get_company_overview(self, symbol: str) -> pd.Series:
        """
        Retrieve company information, financial ratios, and other key metrics.

        Args:
            symbol: Ticker, e.g. 'IBM'.

        Returns:
            pd.Series indexed by field name (e.g. 'MarketCapitalization', 'PERatio').
            Values are returned as-is from AV (strings); convert as needed.
        """
        data = self._make_request({"function": "OVERVIEW", "symbol": symbol})
        return pd.Series(data)

    def get_company_logo(self, symbol: str) -> dict:
        """
        Retrieve PNG and SVG logo URLs for a company.

        Args:
            symbol: Ticker, e.g. 'IBM'.

        Returns:
            dict with keys 'symbol', 'logo_url_png', 'logo_url_svg'.
        """
        return self._make_request({"function": "COMPANY_LOGO", "symbol": symbol})

    def get_etf_profile(self, symbol: str) -> dict:
        """
        Retrieve ETF metrics along with sector and holdings breakdowns.

        Args:
            symbol: ETF ticker, e.g. 'QQQ'.

        Returns:
            dict with scalar metrics (e.g. 'net_assets', 'net_expense_ratio',
            'inception_date') plus 'sectors' and 'holdings' as DataFrames.
        """
        data = self._make_request({"function": "ETF_PROFILE", "symbol": symbol})
        profile = {k: v for k, v in data.items() if k not in ("sectors", "holdings")}
        profile["sectors"] = self._coerce_numeric_columns(
            pd.DataFrame.from_records(data.get("sectors", []))
        )
        profile["holdings"] = self._coerce_numeric_columns(
            pd.DataFrame.from_records(data.get("holdings", []))
        )
        return profile

    def get_dividends(self, symbol: str) -> pd.DataFrame:
        """
        Retrieve historical and declared future dividend distributions.

        Args:
            symbol: Ticker, e.g. 'IBM'.

        Returns:
            pd.DataFrame indexed by ex_dividend_date (ascending), with columns
            declaration_date, record_date, payment_date, amount.
        """
        data = self._make_request({"function": "DIVIDENDS", "symbol": symbol})
        return self._records_to_frame(data.get("data", []), "ex_dividend_date")

    def get_splits(self, symbol: str) -> pd.DataFrame:
        """
        Retrieve historical stock split events.

        Args:
            symbol: Ticker, e.g. 'IBM'.

        Returns:
            pd.DataFrame indexed by effective_date (ascending), with column
            split_factor.
        """
        data = self._make_request({"function": "SPLITS", "symbol": symbol})
        return self._records_to_frame(data.get("data", []), "effective_date")

    def get_shares_outstanding(self, symbol: str) -> pd.DataFrame:
        """
        Retrieve quarterly diluted and basic shares outstanding.

        Args:
            symbol: Ticker, e.g. 'MSFT'.

        Returns:
            pd.DataFrame indexed by date (ascending), with columns
            shares_outstanding_diluted, shares_outstanding_basic.
        """
        data = self._make_request({"function": "SHARES_OUTSTANDING", "symbol": symbol})
        return self._records_to_frame(data.get("data", []), "date")

    def get_income_statement(self, symbol: str) -> Dict[str, pd.DataFrame]:
        """
        Retrieve annual and quarterly income statements.

        Args:
            symbol: Ticker, e.g. 'IBM'.

        Returns:
            dict with keys 'annual' and 'quarterly', each a pd.DataFrame
            indexed by fiscalDateEnding (ascending).
        """
        return self._get_financial_statement("INCOME_STATEMENT", symbol)

    def get_balance_sheet(self, symbol: str) -> Dict[str, pd.DataFrame]:
        """
        Retrieve annual and quarterly balance sheets.

        Args:
            symbol: Ticker, e.g. 'IBM'.

        Returns:
            dict with keys 'annual' and 'quarterly', each a pd.DataFrame
            indexed by fiscalDateEnding (ascending).
        """
        return self._get_financial_statement("BALANCE_SHEET", symbol)

    def get_cash_flow(self, symbol: str) -> Dict[str, pd.DataFrame]:
        """
        Retrieve annual and quarterly cash flow statements.

        Args:
            symbol: Ticker, e.g. 'IBM'.

        Returns:
            dict with keys 'annual' and 'quarterly', each a pd.DataFrame
            indexed by fiscalDateEnding (ascending).
        """
        return self._get_financial_statement("CASH_FLOW", symbol)

    def get_earnings(self, symbol: str) -> Dict[str, pd.DataFrame]:
        """
        Retrieve annual and quarterly EPS, including quarterly analyst
        estimates and surprise metrics.

        Args:
            symbol: Ticker, e.g. 'IBM'.

        Returns:
            dict with keys 'annual' and 'quarterly', each a pd.DataFrame
            indexed by fiscalDateEnding (ascending).
        """
        data = self._make_request({"function": "EARNINGS", "symbol": symbol})
        return {
            "annual": self._records_to_frame(data.get("annualEarnings", []), "fiscalDateEnding"),
            "quarterly": self._records_to_frame(data.get("quarterlyEarnings", []), "fiscalDateEnding"),
        }

    def get_earnings_estimates(self, symbol: str) -> pd.DataFrame:
        """
        Retrieve annual and quarterly EPS/revenue estimates with revision history.

        Args:
            symbol: Ticker, e.g. 'IBM'.

        Returns:
            pd.DataFrame indexed by date (ascending), with a 'horizon' column
            ('fiscal year' or 'quarter') distinguishing annual from quarterly rows.
        """
        data = self._make_request({"function": "EARNINGS_ESTIMATES", "symbol": symbol})
        return self._records_to_frame(data.get("estimates", []), "date")

    def get_listing_status(
        self, date: Optional[str] = None, state: str = "active"
    ) -> pd.DataFrame:
        """
        Retrieve a list of active or delisted US stocks and ETFs.

        Args:
            date: Historical date (YYYY-MM-DD, >= 2010-01-01) to query the
                listing state as of that day. Defaults to the latest trading day.
            state: 'active' or 'delisted'.

        Returns:
            pd.DataFrame with columns symbol, name, exchange, assetType,
            ipoDate, delistingDate, status.
        """
        if state not in {"active", "delisted"}:
            raise ValueError("state must be 'active' or 'delisted'")
        if date is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError(f"date must be in YYYY-MM-DD format, got {date!r}")

        return self._make_csv_request({"function": "LISTING_STATUS", "date": date, "state": state})

    def get_earnings_calendar(
        self, symbol: Optional[str] = None, horizon: str = "3month"
    ) -> pd.DataFrame:
        """
        Retrieve company earnings expected in the next 3, 6, or 12 months.

        Args:
            symbol: Restrict to a single ticker. Defaults to the full calendar.
            horizon: '3month', '6month', or '12month'.

        Returns:
            pd.DataFrame with columns symbol, name, reportDate, fiscalDateEnding,
            estimate, currency, timeOfTheDay.
        """
        if horizon not in {"3month", "6month", "12month"}:
            raise ValueError("horizon must be '3month', '6month', or '12month'")

        return self._make_csv_request(
            {"function": "EARNINGS_CALENDAR", "symbol": symbol, "horizon": horizon}
        )

    def get_ipo_calendar(self) -> pd.DataFrame:
        """
        Retrieve IPOs expected in the next 3 months.

        Returns:
            pd.DataFrame with columns symbol, name, ipoDate, priceRangeLow,
            priceRangeHigh, currency, exchange.
        """
        return self._make_csv_request({"function": "IPO_CALENDAR"})
