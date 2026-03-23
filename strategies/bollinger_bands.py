"""
strategies/bollinger_bands.py — Aggressive Mean Reversion (Bollinger Bands).

Entry Logic (Aggressive):
  - Long:  Price close below Lower Band. Immediate buy on next candle.
  - Short: Price close above Upper Band. Immediate sell on next candle.
  - Exit:  Closes current position as soon as price touches the OTHER band.
"""
import logging
from collections import deque
from typing import Deque

from strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)


class BollingerBandsStrategy(BaseStrategy):
    """Aggressive Bollinger Bands Mean Reversion."""

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

        # Internal state
        self._closes: Deque[float] = deque(maxlen=max(bb_period, rsi_period + 1))
        self._highs:  Deque[float] = deque(maxlen=atr_period + 1)
        self._lows:   Deque[float] = deque(maxlen=atr_period + 1)
        self._prev_close: float = 0.0
        self.last_atr: float = 0.0

    def reset(self):
        """Clear all rolling state for a fresh backtest run."""
        self._closes.clear()
        self._highs.clear()
        self._lows.clear()
        self._prev_close = 0.0
        self.last_atr = 0.0

    def on_candle(self, candle: dict) -> Signal:
        """Process one candle and return BUY / SELL / HOLD."""
        close = float(candle["close"])
        high  = float(candle["high"])
        low   = float(candle["low"])

        self._closes.append(close)
        self._highs.append(high)
        self._lows.append(low)

        # Warmup Check
        warmup = max(self.bb_period, self.rsi_period + 1, self.atr_period + 1)
        if len(self._closes) < warmup:
            self._prev_close = close
            return Signal.HOLD

        # ── Indicator Calculation (Original SMA versions) ────────────────
        closes_list = list(self._closes)
        bb_closes   = closes_list[-self.bb_period:]
        sma         = sum(bb_closes) / len(bb_closes)
        variance    = sum((x - sma) ** 2 for x in bb_closes) / len(bb_closes)
        std         = variance ** 0.5
        upper       = sma + self.bb_std_dev * std
        lower       = sma - self.bb_std_dev * std

        rsi = self._compute_rsi(closes_list)
        self.last_atr = self._compute_atr()

        # ── Signal Logic (Aggressive Mean Reversion) ─────────────────
        final_signal = Signal.HOLD

        # Entry/Exit Logic:
        # Long when price is below lower band.
        # Short when price is above upper band.
        # The engine naturally handles 'flipping' (exiting at opposite band).
        
        if close < lower:
            # Optional: could still use rsi < oversold as a filter, but user asked for aggressive.
            # We'll stick to pure BB touch for maximum aggression.
            final_signal = Signal.BUY
        elif close > upper:
            final_signal = Signal.SELL

        self._prev_close = close
        return final_signal

    def _compute_rsi(self, closes: list) -> float:
        period = self.rsi_period
        deltas = [closes[i] - closes[i - 1] for i in range(-period, 0)]
        gains  = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        avg_gain = sum(gains) / period if gains else 0.0
        avg_loss = sum(losses) / period if losses else 0.0
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _compute_atr(self) -> float:
        highs = list(self._highs)
        lows  = list(self._lows)
        n = min(len(highs), len(lows), self.atr_period + 1)
        if n < 2: return 0.0
        true_ranges = []
        for i in range(1, n):
            prev_mid = (highs[i - 1] + lows[i - 1]) / 2
            tr = max(highs[i]-lows[i], abs(highs[i]-prev_mid), abs(lows[i]-prev_mid))
            true_ranges.append(tr)
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0

    def describe(self) -> dict:
        return {
            "strategy":       self.name,
            "bb_period":      self.bb_period,
            "bb_std_dev":     self.bb_std_dev,
            "rsi_period":     self.rsi_period,
            "rsi_oversold":   self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
            "atr_period":     self.atr_period,
            "version":        "aggressive",
        }
