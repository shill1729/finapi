"""
Quick smoke test for Alpha Vantage and Finnhub wrappers.
Run from the repo root with the venv active:
    python main.py
"""
import logging
import sys

import pandas as pd

from finapi import Clients
from finapi.finnhub import get_quote_from_finnhub, update_with_rt_quotes_from_finnhub
from finapi.utils import Period, Interval, RateLimiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)


def section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def ok(label: str, value) -> None:
    print(f"  ✓ {label}: {value}")


def main() -> None:
    clients = Clients()

    # ------------------------------------------------------------------
    # Alpha Vantage — equity historical data
    # ------------------------------------------------------------------
    section("AV: Daily equity — AAPL (last 5 rows)")
    aapl = clients.av_client.get_historical_data("AAPL", Period.DAILY, adjusted=True)
    print(aapl.tail())
    ok("dtype", aapl.dtype)
    ok("index type", type(aapl.index).__name__)

    # ------------------------------------------------------------------
    # Alpha Vantage — crypto historical data
    # ------------------------------------------------------------------
    section("AV: Daily crypto — BTC (last 5 rows)")
    btc = clients.av_client.get_historical_data("BTC", Period.DAILY)
    print(btc.tail())
    ok("most recent date", btc.index[-1].date())

    # ------------------------------------------------------------------
    # Alpha Vantage — multi-symbol batch
    # ------------------------------------------------------------------
    section("AV: Multi-symbol batch — MSFT + ETH (last 3 rows)")
    batch = clients.av_client.get_assets(["MSFT", "ETH"], Period.DAILY)
    print(batch.tail(3))
    ok("shape", batch.shape)
    ok("columns", list(batch.columns))

    # ------------------------------------------------------------------
    # Alpha Vantage — options chain (most recent session)
    # ------------------------------------------------------------------
    section("AV: Options chain — SPY calls (first 5 rows)")
    chain = clients.av_client.get_options_chain("SPY", option_type="call")
    if chain.empty:
        print("  (no data returned — may be outside market hours or AV free-tier limit)")
    else:
        print(chain[["expiration", "strike", "bid", "ask", "implied_volatility", "delta"]].head())
        ok("total contracts", len(chain))

    # ------------------------------------------------------------------
    # Finnhub — real-time quotes
    # ------------------------------------------------------------------
    section("Finnhub: Real-time quotes — AAPL, MSFT, NVDA")
    fh_limiter = RateLimiter(calls_per_minute=150)
    symbols = ["AAPL", "MSFT", "NVDA"]
    quotes = get_quote_from_finnhub(symbols, clients.finnhub_client, fh_limiter)
    for sym, price in zip(symbols, quotes):
        ok(sym, f"${price:.2f}")

    # ------------------------------------------------------------------
    # Finnhub — update DataFrame with today's quotes
    # ------------------------------------------------------------------
    section("Finnhub: update_with_rt_quotes — inject today's row")
    # Seed a tiny prices DataFrame with yesterday's fake close prices
    yesterday = pd.Timestamp.now("UTC").normalize().tz_localize(None) - pd.Timedelta(days=1)
    seed = pd.DataFrame([[182.0, 415.0, 890.0]], columns=symbols, index=[yesterday])
    updated = update_with_rt_quotes_from_finnhub(seed, clients.finnhub_client, fh_limiter)
    print(updated)
    ok("rows after update", len(updated))
    assert len(updated) == 2, "Expected seed row + today's row"

    print("\nAll sections completed.\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.exception("Test failed: %s", exc)
        sys.exit(1)
