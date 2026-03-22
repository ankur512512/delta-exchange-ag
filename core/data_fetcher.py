"""
core/data_fetcher.py — Paginated OHLCV data fetcher for Delta Exchange.

Handles the 2000-candle-per-request API limit automatically by splitting
the overall date range into chunks and stitching the results together.

Data is optionally cached as CSV on disk to avoid redundant API calls.
"""
import os
import time
import logging
from datetime import datetime, timezone

import pandas as pd

import config
from core.delta_client import DeltaClient

logger = logging.getLogger(__name__)

# Map human-friendly resolution strings to seconds per candle
RESOLUTION_SECONDS = {
    "1m":   60,
    "3m":   180,
    "5m":   300,
    "15m":  900,
    "30m":  1_800,
    "1h":   3_600,
    "2h":   7_200,
    "4h":   14_400,
    "6h":   21_600,
    "1d":   86_400,
    "1w":   604_800,
}


class DataFetcher:
    """
    Fetches historical OHLCV candles from Delta Exchange India.

    Usage:
        fetcher = DataFetcher()
        df = fetcher.fetch("BTCUSD", "5m", "2024-03-21", "2025-03-21")
    """

    def __init__(self, client: DeltaClient = None):
        self.client = client or DeltaClient()

    # ─────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────

    def fetch(
        self,
        symbol: str,
        resolution: str,
        start_date: str,
        end_date: str,
        use_cache: bool = None,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data for the full date range, paginating automatically.

        Args:
            symbol:     Trading pair, e.g. "BTCUSD"
            resolution: Candle size, e.g. "5m", "15m", "1h"
            start_date: ISO date string "YYYY-MM-DD" (UTC)
            end_date:   ISO date string "YYYY-MM-DD" (UTC)
            use_cache:  Override config.USE_CACHE if provided

        Returns:
            pd.DataFrame with columns: [time, open, high, low, close, volume]
            Indexed by 'time' (UTC datetime), sorted oldest-first.
        """
        use_cache = config.USE_CACHE if use_cache is None else use_cache

        if resolution not in RESOLUTION_SECONDS:
            raise ValueError(
                f"Unknown resolution '{resolution}'. "
                f"Valid options: {list(RESOLUTION_SECONDS.keys())}"
            )

        cache_path = self._cache_path(symbol, resolution, start_date, end_date)

        if use_cache and os.path.exists(cache_path):
            logger.info(f"Loading from cache: {cache_path}")
            df = pd.read_csv(cache_path, parse_dates=["time"], index_col="time")
            # Ensure timezone is correctly set to IST after loading from cache
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            df.index = df.index.tz_convert("Asia/Kolkata")
            logger.info(f"Loaded {len(df):,} candles from cache.")
            return df

        logger.info(
            f"Fetching {symbol} {resolution} candles from {start_date} to {end_date}..."
        )
        df = self._fetch_paginated(symbol, resolution, start_date, end_date)

        if use_cache and not df.empty:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            df.to_csv(cache_path)
            logger.info(f"Cached {len(df):,} candles → {cache_path}")

        return df

    # ─────────────────────────────────────────────
    #  Internal helpers
    # ─────────────────────────────────────────────

    def _fetch_paginated(
        self, symbol: str, resolution: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """Split date range into ≤2000-candle chunks and stitch results."""
        candle_secs = RESOLUTION_SECONDS[resolution]
        chunk_secs = config.MAX_CANDLES_PER_REQUEST * candle_secs

        start_ts = self._to_unix(start_date)
        end_ts = self._to_unix(end_date)

        all_candles = []
        chunk_start = start_ts
        request_count = 0

        while chunk_start < end_ts:
            chunk_end = min(chunk_start + chunk_secs, end_ts)

            logger.debug(
                f"  Chunk {request_count + 1}: "
                f"{self._from_unix(chunk_start)} → {self._from_unix(chunk_end)}"
            )

            candles = self.client.get_candles(symbol, resolution, chunk_start, chunk_end)
            if candles:
                all_candles.extend(candles)

            chunk_start = chunk_end
            request_count += 1

            # Respect API rate limits between requests
            if chunk_start < end_ts:
                time.sleep(config.API_REQUEST_DELAY_SECS)

        logger.info(
            f"Fetched {len(all_candles):,} candles in {request_count} API requests."
        )

        if not all_candles:
            logger.warning("No candles returned from API.")
            return pd.DataFrame()

        return self._to_dataframe(all_candles)

    def _to_dataframe(self, candles: list) -> pd.DataFrame:
        """Convert raw API candle list to a clean DataFrame."""
        df = pd.DataFrame(candles)

        # Delta API returns 'time' as Unix seconds
        # Convert to UTC first, then localize to IST (UTC+5:30)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df["time"] = df["time"].dt.tz_convert("Asia/Kolkata")
        df = df.rename(columns={"time": "time"})
        df = df.set_index("time")

        # Ensure numeric types
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Sort ascending and drop duplicates
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="last")]

        return df[["open", "high", "low", "close", "volume"]]

    @staticmethod
    def _to_unix(date_str: str) -> int:
        """Convert 'YYYY-MM-DD' string to Unix timestamp (seconds, UTC)."""
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return int(dt.timestamp())

    @staticmethod
    def _from_unix(ts: int) -> str:
        """Convert Unix timestamp to human-readable UTC string."""
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _cache_path(symbol: str, resolution: str, start: str, end: str) -> str:
        """Build a deterministic cache file path."""
        filename = f"{symbol}_{resolution}_{start}_{end}.csv"
        return os.path.join(config.CACHE_DIR, filename)
