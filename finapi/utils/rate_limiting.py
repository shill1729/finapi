from __future__ import annotations

import threading
import time


class RateLimiter:
    """
    Minimum-interval rate limiter. Thread-safe.

    Each call to wait() blocks until the minimum interval since the previous
    call has elapsed, then records the current time as the new baseline.

    Example:
        limiter = RateLimiter(calls_per_minute=75)
        for symbol in symbols:
            limiter.wait()
            fetch(symbol)
    """

    def __init__(self, calls_per_minute: float):
        if calls_per_minute <= 0:
            raise ValueError("calls_per_minute must be positive")
        self._min_interval = 60.0 / calls_per_minute
        self._last_call: float = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        """Block until it is safe to make the next call."""
        with self._lock:
            elapsed = time.monotonic() - self._last_call
            delay = self._min_interval - elapsed
            if delay > 0:
                time.sleep(delay)
            self._last_call = time.monotonic()
