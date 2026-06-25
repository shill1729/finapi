from __future__ import annotations

import os
from typing import Optional

import finnhub
from finnhub import Client as FinnhubClient

from .alphavantage import AlphaVantageAPI
from .robinhoodcrypto import CryptoAPITradingV2


class Clients:
    """
    Lazy-initializing container for all three API clients.

    Constructing this class validates nothing and makes no network calls.
    Each client is created on first access; a missing environment variable
    raises ValueError at that point, not at construction time. This lets you
    import and partially use the package even if you only have some credentials.

    Env vars required:
        FINNHUB_API_KEY        → finnhub_client
        ALPHA_VANTAGE_API_KEY  → av_client
        ROBINHOOD_PUBLIC_KEY   → rh_client
        ROBINHOOD_API_KEY      → rh_client
    """

    def __init__(self):
        self._finnhub: Optional[FinnhubClient] = None
        self._av: Optional[AlphaVantageAPI] = None
        self._rh: Optional[CryptoAPITradingV2] = None

    @property
    def finnhub_client(self) -> FinnhubClient:
        if self._finnhub is None:
            key = os.getenv("FINNHUB_API_KEY")
            if not key:
                raise ValueError("FINNHUB_API_KEY environment variable is not set.")
            self._finnhub = finnhub.Client(api_key=key)
        return self._finnhub

    @property
    def av_client(self) -> AlphaVantageAPI:
        if self._av is None:
            key = os.getenv("ALPHA_VANTAGE_API_KEY")
            if not key:
                raise ValueError("ALPHA_VANTAGE_API_KEY environment variable is not set.")
            self._av = AlphaVantageAPI(api_key=key)
        return self._av

    @property
    def rh_client(self) -> CryptoAPITradingV2:
        if self._rh is None:
            self._rh = CryptoAPITradingV2()
        return self._rh
