"""
strategies/fast_ema_cross.py — Fast EMA Crossover with Macro Trend Filter.

Entry Logic:
  - Long:  Fast EMA > Slow EMA AND Close > 200 EMA
  - Short: Fast EMA < Slow EMA AND Close < 200 EMA
  - Neutral / Exit: Fast EMA crosses opposite direction, or SL hit.
"""
import logging
from typing import Optional
import config
from strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)

class EmaCrossStrategy(BaseStrategy):
    """Trend-Following EMA Crossover filtered by 200 EMA."""

    name = "ema_cross"

    def __init__(
        self,
        ema_fast: int = 9,
        ema_slow: int = 21,
        ema_trend: int = 200,
        atr_multiplier: float = 2.0,
        atr_period: int = 14,
    ):
        self.period_fast = ema_fast
        self.period_slow = ema_slow
        self.period_trend = ema_trend
        
        self.atr_multiplier = atr_multiplier
        self.atr_period = atr_period

        # Internal State
        self.ema_fast: Optional[float] = None
        self.ema_slow: Optional[float] = None
        self.ema_trend: Optional[float] = None
        
        self.candle_count = 0
        self.warmup_required = self.period_trend

        # ATR state
        self.tr_list: list = []
        self.last_atr: float = 0.0
        self.prev_close: Optional[float] = None
        
        self.prev_state: Optional[str] = None

    def reset(self):
        """Clear state for a fresh run."""
        self.ema_fast = None
        self.ema_slow = None
        self.ema_trend = None
        self.candle_count = 0
        
        self.tr_list.clear()
        self.last_atr = 0.0
        self.prev_close = None
        self.prev_state = None

    def get_trailing_sl(self, side: str, current_sl: float, price: float, atr: float) -> float:
        """Ratchets behind price using basic ATR distance."""
        if not getattr(config, "TRAILING_STOP_ENABLED", True):
            return current_sl
            
        trail_distance = atr * self.atr_multiplier
        if side == "long":
            new_sl = price - trail_distance
            return max(current_sl, new_sl)
        else:
            new_sl = price + trail_distance
            return min(current_sl, new_sl)

    def _calc_ema(self, current: float, previous: Optional[float], length: int) -> float:
        alpha = 2.0 / (length + 1)
        if previous is None:
            return current
        return alpha * current + (1 - alpha) * previous

    def on_candle(self, candle: dict) -> Signal:
        close = float(candle["close"])
        high  = float(candle["high"])
        low   = float(candle["low"])
        
        self.candle_count += 1
        
        # ── 1. Update EMAs
        self.ema_fast = self._calc_ema(close, self.ema_fast, self.period_fast)
        self.ema_slow = self._calc_ema(close, self.ema_slow, self.period_slow)
        self.ema_trend = self._calc_ema(close, self.ema_trend, self.period_trend)

        # ── 2. Calculate ATR using Wilder's Smoothing
        if self.prev_close is not None:
            tr = max(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
            if self.candle_count <= self.atr_period + 1:
                self.tr_list.append(tr)
                if len(self.tr_list) == self.atr_period:
                    self.last_atr = sum(self.tr_list) / self.atr_period
            else:
                self.last_atr = (self.last_atr * (self.atr_period - 1) + tr) / self.atr_period

        self.prev_close = close

        # ── 3. Signal Generation
        if self.candle_count < self.warmup_required:
            return Signal.HOLD

        final_signal = Signal.HOLD

        trend_up = close > self.ema_trend
        trend_dn = close < self.ema_trend

        # Entry logic
        if trend_up and self.ema_fast > self.ema_slow:
            if self.prev_state != "LONG":
                final_signal = Signal.BUY
                logger.info(f"BUY SIGNAL | Fast EMA crossed UP | Close > 200 EMA ({self.ema_trend:.2f})")
                self.prev_state = "LONG"
                
        elif trend_dn and self.ema_fast < self.ema_slow:
            if self.prev_state != "SHORT":
                final_signal = Signal.SELL
                logger.info(f"SELL SIGNAL | Fast EMA crossed DOWN | Close < 200 EMA ({self.ema_trend:.2f})")
                self.prev_state = "SHORT"
                
        else:
            # Exit flip triggers Hold neutralizing
            if (self.prev_state == "LONG" and self.ema_fast < self.ema_slow) or (self.prev_state == "SHORT" and self.ema_fast > self.ema_slow):
                self.prev_state = "NEUTRAL"

        return final_signal

    def get_state_str(self) -> str:
        f = f"{self.ema_fast:.1f}" if self.ema_fast else "--"
        s = f"{self.ema_slow:.1f}" if self.ema_slow else "--"
        t = f"{self.ema_trend:.1f}" if self.ema_trend else "--"
        return f" | F:{f} S:{s} | Macro:{t}"

    def describe(self) -> dict:
        return {
            "strategy":       self.name,
            "period_fast":    self.period_fast,
            "period_slow":    self.period_slow,
            "period_trend":   self.period_trend,
            "atr_multiplier": self.atr_multiplier,
            "version":        "ema-crossover-macro-v1"
        }
