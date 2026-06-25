from __future__ import annotations

import logging

import requests
from requests.adapters import HTTPAdapter
from typing import Optional
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class RequestRetryHandler:
    """
    Wraps requests.Session with automatic retry logic via urllib3.

    Retries only GET requests (safe/idempotent). POST requests are not
    retried to prevent duplicate side effects (e.g. duplicate orders).

    Backoff between retries follows: backoff_factor * 2^attempt seconds.
    With the default backoff_factor=0.5: 0.5s, 1s, 2s, 4s, 8s.
    """

    def __init__(
        self,
        max_retries: int = 5,
        backoff_factor: float = 0.5,
        status_forcelist: Optional[list] = None,
    ):
        statuses = frozenset(status_forcelist or [429, 500, 502, 503, 504])
        retry = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=statuses,
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session = requests.Session()
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """
        Perform a request. Retries are handled automatically by the adapter for GETs.

        Args:
            method: HTTP method string (e.g. 'GET').
            url: Request URL.
            **kwargs: Passed through to requests.Session.request.

        Returns:
            requests.Response — caller is responsible for raise_for_status().

        Raises:
            requests.RequestException: If the request fails irrecoverably.
        """
        try:
            return self.session.request(method, url, **kwargs)
        except requests.RequestException as e:
            logger.error("Request to %s failed: %s", url, e)
            raise
