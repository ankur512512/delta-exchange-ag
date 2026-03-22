"""
strategies/bollinger_bands.py — Bollinger Bands + RSI filter strategy.

Entry Logic:
  BUY  when price closes BELOW the lower Bollinger Band AND RSI < rsi_oversold
  SELL when price closes ABOVE the upper Bollinger Band AND RSI > rsi_overbought
"""
import logging
from collections import deque
from typing import Deque

from strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)


class BollingerBandsStrategy(BaseStrategy):
    """Bollinger Bands mean-reversion strategy with RSI confirmation filter."""

    name = "bollinger_bands"

    def __init__(
        self,
        bb_period:      int   = 20,
        bb_std_dev:     float = 2.0,
        rsi_period:     int   = 14,
        rsi_oversold:   float = 35.0,
        rsi_overbought: float = 65.0,
        atr_period:     int   = 14,
    ):
        self.bb_period      = bb_period
        self.bb_std_dev     = bb_std_dev
        self.rsi_period     = rsi_period
        self.rsi_oversold   = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.atr_period     = atr_period

        # Internal rolling window
        self._closes: Deque[float] = deque(maxlen=bb_period)
        self._highs:  Deque[float] = deque(maxlen=atr_period + 1)
        self._lows:   Deque[float] = deque(maxlen=atr_period + 1)
        
        # Exponential smoothing state for RSI and ATR (Wilder's Smoothing)
        self._avg_gain: float = 0.0
        self._avg_loss: float = 0.0
        self._avg_tr:   float = 0.0
        self._prev_close: float = 0.0
        self._warmup_count: int = 0
        self.last_atr: float = 0.0

    def reset(self):
        """Clear all rolling state for a fresh backtest run."""
        self._closes.clear()
        self._highs.clear()
        self._lows.clear()
        self._avg_gain = 0.0
        self._avg_loss = 0.0
        self._avg_tr = 0.0
        self._prev_close = 0.0
        self._warmup_count = 0
        self.last_atr = 0.0

    def on_candle(self, candle: dict) -> Signal:
        """Process one candle and return BUY / SELL / HOLD."""
        close = float(candle["close"])
        high  = float(candle["high"])
        low   = float(candle["low"])

        # ── Indicator Calculation (Standard Wilder's Method) ────────────────
        if self._prev_close == 0:
            # Seed state on first candle
            tr = high - low
            gain = 0.0
            loss = 0.0
        else:
            tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
            diff = close - self._prev_close
            gain = max(diff, 0)
            loss = max(-diff, 0)

        self._closes.append(close)
        self._warmup_count += 1

        # Exponential Smoothing (Running Moving Average)
        if self._warmup_count <= self.rsi_period:
            # Simple average for the first 'n' periods to seed the EMA
            self._avg_gain += gain / self.rsi_period
            self._avg_loss += loss / self.rsi_period
            self._avg_tr   += tr / self.atr_period
        else:
            # Wilder's Smoothing formula: NewAvg = (PrevAvg * (n-1) + Current) / n
            alpha_rsi = 1.0 / self.rsi_period
            self._avg_gain = (gain * alpha_rsi) + (self._avg_gain * (1 - alpha_rsi))
            self._avg_loss = (loss * alpha_rsi) + (self._avg_loss * (1 - alpha_rsi))
            
            alpha_atr = 1.0 / self.atr_period
            self._avg_tr = (tr * alpha_atr) + (self._avg_tr * (1 - alpha_atr))

        self.last_atr = self._avg_tr
        self._prev_close = close

        # Wait for full window warmup
        if self._warmup_count < max(self.bb_period, self.rsi_period):
            return Signal.HOLD

        # ── Bollinger Bands ──────────────────────────────
        bb_list = list(self._closes)
        sma = sum(bb_list) / len(bb_list)
        variance = sum((x - sma) ** 2 for x in bb_list) / len(bb_list)
        std = variance ** 0.5
        upper = sma + self.bb_std_dev * std
        lower = sma - self.bb_std_dev * std

        # ── RSI ──────────────────────────────────────────
        if self._avg_loss == 0:
            rsi = 100.0 if self._avg_gain > 0 else 50.0
        else:
            rs = self._avg_gain / self._avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # ── Signal ───────────────────────────────────────
        if close < lower and rsi < self.rsi_oversold:
            return Signal.BUY
        elif close > upper and rsi > self.rsi_overbought:
            return Signal.SELL

        return Signal.HOLD

    def describe(self) -> dict:
        return {
            "strategy":       self.name,
            "bb_period":      self.bb_period,
            "bb_std_dev":     self.bb_std_dev,
            "rsi_period":     self.rsi_period,
            "rsi_oversold":   self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
            "atr_period":     self.atr_period,
        }
