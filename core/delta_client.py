"""
core/delta_client.py — Delta Exchange India REST API client.

Handles:
- Unauthenticated requests (OHLCV, ticker, products)
- Authenticated requests (wallet, orders, positions) using HMAC-SHA256 signing
- Rate limit handling with exponential backoff on HTTP 429
"""
import hashlib
import hmac
import time
import logging
import requests
from typing import Optional

import config

logger = logging.getLogger(__name__)


class DeltaClient:
    """Thin wrapper around the Delta Exchange India REST API."""

    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.base_url = config.BASE_URL
        self.api_key = api_key or config.API_KEY
        self.api_secret = api_secret or config.API_SECRET
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    # ─────────────────────────────────────────────
    #  Authentication helpers
    # ─────────────────────────────────────────────

    def _generate_signature(self, method: str, path: str, query_string: str, body: str, timestamp: str) -> str:
        """Generate HMAC-SHA256 signature as required by Delta Exchange."""
        message = method + timestamp + path
        if query_string:
            message += "?" + query_string
        if body:
            message += body
        return hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

    def _auth_headers(self, method: str, path: str, query_string: str = "", body: str = "") -> dict:
        """Build authentication headers for private endpoints."""
        timestamp = str(int(time.time()))
        signature = self._generate_signature(method, path, query_string, body, timestamp)
        return {
            "api-key": self.api_key,
            "timestamp": timestamp,
            "signature": signature,
            "Content-Type": "application/json",
        }

    # ─────────────────────────────────────────────
    #  HTTP helpers
    # ─────────────────────────────────────────────

    def _get(self, path: str, params: dict = None, authenticated: bool = False, retries: int = 5) -> dict:
        """Make an authenticated or unauthenticated GET request with retry on 429."""
        url = self.base_url + path
        params = params or {}
        query_string = "&".join(f"{k}={v}" for k, v in sorted(params.items())) if authenticated else ""

        headers = {}
        if authenticated:
            headers = self._auth_headers("GET", path, query_string=query_string)

        for attempt in range(retries):
            resp = self.session.get(url, params=params, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                reset_ms = int(resp.headers.get("X-RATE-LIMIT-RESET", 5000))
                wait = reset_ms / 1000.0 + (2 ** attempt)
                logger.warning(f"Rate limited (429). Waiting {wait:.1f}s before retry {attempt + 1}/{retries}...")
                time.sleep(wait)
            else:
                resp.raise_for_status()
        raise RuntimeError(f"Failed GET {path} after {retries} retries.")

    def _post(self, path: str, body: dict, retries: int = 3) -> dict:
        """Make an authenticated POST request."""
        import json
        url = self.base_url + path
        body_str = json.dumps(body, separators=(",", ":"))
        headers = self._auth_headers("POST", path, body=body_str)

        for attempt in range(retries):
            resp = self.session.post(url, data=body_str, headers=headers)
            if resp.status_code in (200, 201):
                return resp.json()
            elif resp.status_code == 429:
                wait = 5 * (2 ** attempt)
                logger.warning(f"Rate limited (429). Waiting {wait}s before retry {attempt + 1}/{retries}...")
                time.sleep(wait)
            else:
                logger.error(f"POST {path} failed: {resp.status_code} — {resp.text}")
                resp.raise_for_status()
        raise RuntimeError(f"Failed POST {path} after {retries} retries.")

    def _delete(self, path: str, body: dict = None, retries: int = 3) -> dict:
        """Make an authenticated DELETE request."""
        import json
        url = self.base_url + path
        body_str = json.dumps(body or {}, separators=(",", ":"))
        headers = self._auth_headers("DELETE", path, body=body_str)

        for attempt in range(retries):
            resp = self.session.delete(url, data=body_str, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                wait = 5 * (2 ** attempt)
                time.sleep(wait)
            else:
                resp.raise_for_status()
        raise RuntimeError(f"Failed DELETE {path} after {retries} retries.")

    # ─────────────────────────────────────────────
    #  Public Market Data
    # ─────────────────────────────────────────────

    def get_candles(self, symbol: str, resolution: str, start_ts: int, end_ts: int) -> list:
        """
        Fetch up to 2000 OHLCV candles for the given time range.
        
        Args:
            symbol:     e.g. "BTCUSD"
            resolution: e.g. "5m", "15m", "1h", "1d"
            start_ts:   Unix timestamp (seconds) for range start
            end_ts:     Unix timestamp (seconds) for range end

        Returns:
            List of candle dicts with keys: time, open, high, low, close, volume
        """
        data = self._get("/history/candles", params={
            "symbol": symbol,
            "resolution": resolution,
            "start": str(start_ts),
            "end": str(end_ts),
        })
        return data.get("result", [])

    def get_ticker(self, symbol: str) -> dict:
        """Fetch the current ticker for a symbol."""
        data = self._get(f"/tickers/{symbol}")
        return data.get("result", {})

    def get_products(self) -> list:
        """Fetch all available products."""
        data = self._get("/products")
        return data.get("result", [])

    # ─────────────────────────────────────────────
    #  Private — Wallet
    # ─────────────────────────────────────────────

    def get_wallet_balance(self, asset: str = "USD") -> float:
        """
        Returns the available balance for the given asset.
        Requires API key/secret.
        """
        data = self._get("/wallets", authenticated=True)
        wallets = data.get("result", [])
        for w in wallets:
            if w.get("asset_symbol") == asset:
                return float(w.get("available_balance", 0))
        logger.warning(f"Asset '{asset}' not found in wallet response.")
        return 0.0

    # ─────────────────────────────────────────────
    #  Private — Orders
    # ─────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,           # "buy" or "sell"
        size: float,         # number of contracts
        order_type: str = "limit_order",
        limit_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> dict:
        """
        Place an order on Delta Exchange.
        In BACKTEST mode this is a no-op (returns a mock response).
        In LIVE mode this sends a real order.
        """
        if config.MODE == "BACKTEST":
            logger.debug(f"[BACKTEST] Simulated order: {side} {size} {symbol} @ {limit_price}")
            return {"result": {"id": "simulated", "status": "open"}}

        body = {
            "product_symbol": symbol,
            "side": side,
            "size": int(size),
            "order_type": order_type,
        }
        if limit_price is not None:
            body["limit_price"] = str(limit_price)
        if stop_loss is not None:
            body["stop_loss_price"] = str(stop_loss)
        if take_profit is not None:
            body["take_profit_price"] = str(take_profit)
        if client_order_id is not None:
            body["client_order_id"] = client_order_id

        logger.info(f"[LIVE] Placing {side} order for {size} {symbol} @ {limit_price}")
        return self._post("/orders", body)

    def cancel_order(self, order_id: str, product_id: int) -> dict:
        """Cancel an open order by ID."""
        if config.MODE == "BACKTEST":
            return {"result": "simulated_cancel"}
        return self._delete("/orders", body={"id": order_id, "product_id": product_id})

    def get_active_orders(self, symbol: str) -> list:
        """Fetch all active orders for a symbol."""
        data = self._get("/orders", params={"product_symbol": symbol}, authenticated=True)
        return data.get("result", [])

    # ─────────────────────────────────────────────
    #  Private — Positions
    # ─────────────────────────────────────────────

    def get_position(self, symbol: str) -> dict:
        """Fetch current open position for a symbol."""
        data = self._get(f"/positions/margined", params={"product_symbol": symbol}, authenticated=True)
        results = data.get("result", [])
        return results[0] if results else {}

    def close_all_positions(self) -> dict:
        """Emergency: close all open positions."""
        if config.MODE == "BACKTEST":
            return {"result": "simulated_close_all"}
        return self._post("/positions/close_all", {})
