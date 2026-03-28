"""
strategies/supertrend_dema.py — Supertrend + DEMA strategy.

Entry Logic:
  - Long:  Price > DEMA and Supertrend signal changes from Sell to Buy.
  - Short: Price < DEMA and Supertrend signal changes from Buy to Sell.
  - Exit:  Automatically via BacktestEngine's Stop Loss (Ratchet to SuperTrend signal line).
"""
import logging
from collections import deque
from typing import Deque, Optional
import config
from strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)


class SupertrendDemaStrategy(BaseStrategy):
    """Supertrend + DEMA Strategy."""

    name = "supertrend_dema"

    def __init__(
        self,
        atr_period: int = 12,
        atr_multiplier: float = 3.0,
        dema_length: int = 200,
    ):
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self.dema_length = dema_length

        # Internal state
        self._prev_close: Optional[float] = None
        self._tr_history: list = []
        
        # Supertrend state
        self.last_atr: float = 0.0
        self.trend: int = 1  # 1 for BUY (UP), -1 for SELL (DOWN)
        self.final_upperband: float = 0.0
        self.final_lowerband: float = 0.0
        self._st_initialized: bool = False
        
        # EMA state for DEMA
        self.ema1: Optional[float] = None
        self.ema2: Optional[float] = None
        
        # Warmup tracker
        self._candle_count: int = 0
        self._warmup_required: int = self.dema_length * 2 # Standard DEMA needs time to converge
        
        self.last_dema: float = 0.0
        self.prev_state: Optional[str] = None # Tracks previous entry condition state

    def get_trailing_sl(self, side: str, current_sl: float, price: float, atr: float) -> float:
        """
        Calculates a new 'ratcheted' stop-loss based on SuperTrend output.
        - Long positions trail at the Final Lowerband (SuperTrend Buy signal line)
        - Short positions trail at the Final Upperband (SuperTrend Sell signal line)
        Ensures the stop loss strictly ratchets in the direction of profit and never widens initial risk.
        """
        if not getattr(config, "TRAILING_STOP_ENABLED", True):
            return current_sl
            
        if side == "long":
            return max(current_sl, self.final_lowerband)
        else:
            return min(current_sl, self.final_upperband)

    def reset(self):
        """Clear all rolling state for a fresh backtest run."""
        self._prev_close = None
        self._tr_history.clear()
        self.last_atr = 0.0
        self.trend = 1
        self.final_upperband = 0.0
        self.final_lowerband = 0.0
        self._st_initialized = False
        self.ema1 = None
        self.ema2 = None
        self._candle_count = 0
        self.last_dema = 0.0
        self.prev_state = None

    def on_candle(self, candle: dict) -> Signal:
        """Process one candle and return BUY / SELL / HOLD."""
        close = float(candle["close"])
        high  = float(candle["high"])
        low   = float(candle["low"])

        self._candle_count += 1
        
        # ── 1. DEMA Calculation ───────────────────────────────────────────
        alpha = 2.0 / (self.dema_length + 1)
        if self.ema1 is None:
            self.ema1 = close
            self.ema2 = close
            self.last_dema = close
        else:
            self.ema1 = alpha * close + (1 - alpha) * self.ema1
            self.ema2 = alpha * self.ema1 + (1 - alpha) * self.ema2
            self.last_dema = 2 * self.ema1 - self.ema2

        # ── 2. Supertrend Calculation ─────────────────────────────────────
        if self._prev_close is None:
            self._prev_close = close
            return Signal.HOLD
            
        hl2 = (high + low) / 2.0
        tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        
        # Calculate RMA for ATR
        if len(self._tr_history) < self.atr_period:
            self._tr_history.append(tr)
            if len(self._tr_history) == self.atr_period:
                self.last_atr = sum(self._tr_history) / self.atr_period
        else:
            self.last_atr = (self.last_atr * (self.atr_period - 1) + tr) / self.atr_period

        # Only process ST bands once ATR is initialized
        if self.last_atr > 0:
            basic_upperband = hl2 + (self.atr_multiplier * self.last_atr)
            basic_lowerband = hl2 - (self.atr_multiplier * self.last_atr)

            # Update final bands
            if not self._st_initialized:
                self.final_upperband = basic_upperband
                self.final_lowerband = basic_lowerband
                self._st_initialized = True
            else:
                if basic_upperband < self.final_upperband or self._prev_close > self.final_upperband:
                    self.final_upperband = basic_upperband
                
                if basic_lowerband > self.final_lowerband or self._prev_close < self.final_lowerband:
                    self.final_lowerband = basic_lowerband

            # Update trend direction
            if self.trend == -1 and close > self.final_upperband:
                self.trend = 1
            elif self.trend == 1 and close < self.final_lowerband:
                self.trend = -1
        
        # Store for next loop
        self._prev_close = close

        # ── 3. Signal Generation ──────────────────────────────────────────
        # Wait for DEMA to warm up
        if self._candle_count < self._warmup_required:
            return Signal.HOLD

        final_signal = Signal.HOLD

        # Long Condition: Close > DEMA and Supertrend is BUY (Trend == 1)
        long_condition = (self.trend == 1) and (close > self.last_dema)
        short_condition = (self.trend == -1) and (close < self.last_dema)

        if long_condition and not short_condition:
            if self.prev_state != "LONG":
                final_signal = Signal.BUY
                logger.info(f"BUY SIGNAL | Close: {close:.2f} > DEMA: {self.last_dema:.2f} | ST is BUY")
                self.prev_state = "LONG"
        elif short_condition and not long_condition:
            if self.prev_state != "SHORT":
                final_signal = Signal.SELL
                logger.info(f"SELL SIGNAL | Close: {close:.2f} < DEMA: {self.last_dema:.2f} | ST is SELL")
                self.prev_state = "SHORT"
        else:
            if self.trend == 1 and not long_condition:
                self.prev_state = "NEUTRAL"
            elif self.trend == -1 and not short_condition:
                self.prev_state = "NEUTRAL"
                
        return final_signal

    def describe(self) -> dict:
        return {
            "strategy":       self.name,
            "atr_period":     self.atr_period,
            "atr_multiplier": self.atr_multiplier,
            "dema_length":    self.dema_length,
            "version":        "supertrend-dema-v1",
        }
