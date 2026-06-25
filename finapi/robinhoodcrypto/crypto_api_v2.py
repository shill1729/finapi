import base64
import datetime
import json
import os
from typing import Any, Dict, Optional

import requests
from nacl.signing import SigningKey


class CryptoAPITradingV2:
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
    def _build_query_string(params: Dict[str, Any]) -> str:
        """Build a query string from a dict, supporting list values for repeated keys."""
        if not params:
            return ""
        parts = []
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, list):
                parts.extend(f"{key}={v}" for v in value)
            else:
                parts.append(f"{key}={value}")
        return "?" + "&".join(parts) if parts else ""

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
                response = requests.post(url, headers=headers, json=json.loads(body) if body else None, timeout=10)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            if response.status_code >= 400:
                try:
                    return response.json()
                except json.JSONDecodeError:
                    return {"error": response.text or response.reason, "status_code": response.status_code}

            return response.json()
        except requests.RequestException as e:
            raise RuntimeError(f"API request failed: {e}") from e

    def get_accounts(self) -> Any:
        return self._make_request("GET", "/api/v2/crypto/trading/accounts/")

    def get_trading_pairs(self, *symbols: str) -> list:
        """Returns all trading pairs, or filtered by symbol (e.g. 'BTC-USD')."""
        params = {"symbol": list(symbols)} if symbols else {}
        path = f"/api/v2/crypto/trading/trading_pairs/{self._build_query_string(params)}"

        all_results = []
        response = self._make_request("GET", path)
        while response:
            all_results.extend(response.get("results", []))
            next_url = response.get("next")
            if not next_url:
                break
            response = self._make_request("GET", next_url.replace(self.BASE_URL, ""))
        return all_results

    def get_holdings(self, account_number: str, *asset_codes: str) -> Any:
        """Returns holdings for an account, optionally filtered by asset code (e.g. 'BTC')."""
        params: Dict[str, Any] = {"account_number": account_number}
        if asset_codes:
            params["asset_code"] = list(asset_codes)
        path = f"/api/v2/crypto/trading/holdings/{self._build_query_string(params)}"
        return self._make_request("GET", path)

    def get_best_bid_ask(self, *symbols: str) -> Any:
        """Returns best bid/ask for the given trading pairs (e.g. 'BTC-USD')."""
        params = {"symbol": list(symbols)} if symbols else {}
        path = f"/api/v2/crypto/marketdata/best_bid_ask/{self._build_query_string(params)}"
        return self._make_request("GET", path)

    def get_estimated_price(self, symbol: str, side: str, quantity: str) -> Any:
        """
        Args:
            symbol: Trading pair, e.g. 'BTC-USD'.
            side: 'bid', 'ask', or 'both'.
            quantity: Comma-separated quantities, e.g. '0.1,1,1.999'.
        """
        params = {"symbol": symbol, "side": side, "quantity": quantity}
        path = f"/api/v2/crypto/trading/estimated_price/{self._build_query_string(params)}"
        return self._make_request("GET", path)

    def place_order(
        self,
        account_number: str,
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
        path = f"/api/v2/crypto/trading/orders/{self._build_query_string({'account_number': account_number})}"
        return self._make_request("POST", path, json.dumps(body))

    def cancel_order(self, order_id: str) -> Any:
        return self._make_request("POST", f"/api/v2/crypto/trading/orders/{order_id}/cancel/")

    def get_order(self, account_number: str, order_id: str) -> Any:
        path = f"/api/v2/crypto/trading/orders/{order_id}/{self._build_query_string({'account_number': account_number})}"
        return self._make_request("GET", path)

    def get_orders(self, account_number: str, created_at_start: Optional[str] = None) -> Any:
        """
        Args:
            account_number: The account to query.
            created_at_start: ISO 8601 timestamp to filter orders from, e.g. '2023-01-01T00:00:00Z'.
        """
        params: Dict[str, Any] = {"account_number": account_number}
        if created_at_start:
            params["created_at_start"] = created_at_start
        path = f"/api/v2/crypto/trading/orders/{self._build_query_string(params)}"
        return self._make_request("GET", path)
