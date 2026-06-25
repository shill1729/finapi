import base64
import datetime
import json
import os
from typing import Any, Dict, Optional

import requests
from nacl.signing import SigningKey


class CryptoAPITrading:
    BASE_URL = "https://trading.robinhood.com"

    def __init__(self):
        api_key = os.getenv("ROBINHOOD_PUBLIC_KEY")
        private_key_b64 = os.getenv("ROBINHOOD_API_KEY")
        if not api_key:
            raise ValueError("ROBINHOOD_PUBLIC_KEY environment variable is not set.")
        if not private_key_b64:
            raise ValueError("ROBINHOOD_API_KEY environment variable is not set.")
        self.api_key = api_key
        self.private_key = SigningKey(base64.b64decode(private_key_b64))

    @staticmethod
    def _get_current_timestamp() -> int:
        return int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())

    @staticmethod
    def _build_query_string(key: str, *args: Optional[str]) -> str:
        if not args:
            return ""
        return "?" + "&".join(f"{key}={arg}" for arg in args)

    def _get_authorization_header(self, method: str, path: str, body: str, timestamp: int) -> Dict[str, str]:
        message = f"{self.api_key}{timestamp}{path}{method}{body}"
        signed = self.private_key.sign(message.encode("utf-8"))
        return {
            "x-api-key": self.api_key,
            "x-signature": base64.b64encode(signed.signature).decode("utf-8"),
            "x-timestamp": str(timestamp),
        }

    def _make_request(self, method: str, path: str, body: str = "") -> Any:
        timestamp = self._get_current_timestamp()
        headers = self._get_authorization_header(method, path, body, timestamp)
        url = self.BASE_URL + path

        try:
            if method == "GET":
                response = requests.get(url, headers=headers, timeout=10)
            elif method == "POST":
                response = requests.post(url, headers=headers, json=json.loads(body), timeout=10)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            return response.json()
        except requests.RequestException as e:
            raise RuntimeError(f"API request failed: {e}") from e

    def get_account(self) -> Any:
        return self._make_request("GET", "/api/v1/crypto/trading/accounts/")

    def get_trading_pairs(self, *symbols: Optional[str]) -> Any:
        """Symbols must be trading pairs, e.g. 'BTC-USD'. Returns all if none given."""
        path = f"/api/v1/crypto/trading/trading_pairs/{self._build_query_string('symbol', *symbols)}"
        return self._make_request("GET", path)

    def get_holdings(self, *asset_codes: Optional[str]) -> Any:
        """Asset codes are short-form, e.g. 'BTC'. Returns all holdings if none given."""
        path = f"/api/v1/crypto/trading/holdings/{self._build_query_string('asset_code', *asset_codes)}"
        return self._make_request("GET", path)

    def get_best_bid_ask(self, *symbols: Optional[str]) -> Any:
        """Symbols must be trading pairs, e.g. 'BTC-USD'. Returns all if none given."""
        path = f"/api/v1/crypto/marketdata/best_bid_ask/{self._build_query_string('symbol', *symbols)}"
        return self._make_request("GET", path)

    def get_estimated_price(self, symbol: str, side: str, quantity: str) -> Any:
        """
        Args:
            symbol: Trading pair, e.g. 'BTC-USD'.
            side: 'bid', 'ask', or 'both'.
            quantity: Comma-separated quantities, e.g. '0.1,1,1.999'.
        """
        path = f"/api/v1/crypto/marketdata/estimated_price/?symbol={symbol}&side={side}&quantity={quantity}"
        return self._make_request("GET", path)

    def place_order(
        self,
        client_order_id: str,
        side: str,
        order_type: str,
        symbol: str,
        order_config: Dict[str, str],
    ) -> Any:
        body = {
            "client_order_id": client_order_id,
            "side": side,
            "type": order_type,
            "symbol": symbol,
            f"{order_type}_order_config": order_config,
        }
        return self._make_request("POST", "/api/v1/crypto/trading/orders/", json.dumps(body))

    def cancel_order(self, order_id: str) -> Any:
        return self._make_request("POST", f"/api/v1/crypto/trading/orders/{order_id}/cancel/")

    def get_order(self, order_id: str) -> Any:
        return self._make_request("GET", f"/api/v1/crypto/trading/orders/{order_id}/")

    def get_orders(self) -> Any:
        return self._make_request("GET", "/api/v1/crypto/trading/orders/")
