"""
strategies/macd_adx_ema.py — Low-Frequency Swing Strategy.

Entry Logic:
  - Long:  Close > EMA(200) AND ADX > 25 AND MACD Histogram crosses above 0
  - Short: Close < EMA(200) AND ADX > 25 AND MACD Histogram crosses below 0
  - Trailing Stop: 2x ATR Ratchet or EMA(200) baseline.
"""
import logging
from typing import Optional
import config
from strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)

class MacdAdxEmaStrategy(BaseStrategy):
    """MACD Momentum + ADX Chop Filter + 200 EMA Swing Trading Strategy."""

    name = "macd_adx_ema"

    def __init__(
        self,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        ema_trend: int = 200,
        atr_multiplier: float = 2.0,
    ):
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        
        self.ema_trend = ema_trend
        self.atr_multiplier = atr_multiplier

        # -- Internal State --
        self.prev_close: Optional[float] = None
        self.prev_high: Optional[float] = None
        self.prev_low: Optional[float] = None
        
        self.candle_count = 0
        self.warmup_required = 300  # Give MACD and ADX time to completely flatten out

        # MACD
        self.ema_fast: Optional[float] = None
        self.ema_slow: Optional[float] = None
        self.macd_line: Optional[float] = None
        self.signal_line: Optional[float] = None
        self.prev_histogram: Optional[float] = None
        self.histogram: float = 0.0

        # Trend EMA
        self.ema_200: Optional[float] = None

        # ADX state
        self.tr_list: list = []
        self.pdm_list: list = []
        self.ndm_list: list = []
        self.dx_list: list = []
        
        self.smooth_tr: float = 0.0
        self.smooth_pdm: float = 0.0
        self.smooth_ndm: float = 0.0
        self.adx: float = 0.0

        # ATR
        self.last_atr: float = 0.0
        
        self.prev_state: Optional[str] = None

    def reset(self):
        """Clear all rolling state for a fresh run."""
        self.prev_close = None
        self.prev_high = None
        self.prev_low = None
        self.candle_count = 0
        self.ema_fast = None
        self.ema_slow = None
        self.macd_line = None
        self.signal_line = None
        self.prev_histogram = None
        self.histogram = 0.0
        self.ema_200 = None
        
        self.tr_list.clear()
        self.pdm_list.clear()
        self.ndm_list.clear()
        self.dx_list.clear()
        
        self.smooth_tr = 0.0
        self.smooth_pdm = 0.0
        self.smooth_ndm = 0.0
        self.adx = 0.0
        
        self.last_atr = 0.0
        self.prev_state = None

    def get_trailing_sl(self, side: str, current_sl: float, price: float, atr: float) -> float:
        """
        Calculates a 'ratcheted' stop-loss trailing using ATR or EMA.
        For a slow swing trader, trailing below the 200 EMA + 2 ATR gives huge breathing room.
        We'll just aggressively ratchet behind the price dynamically using 2x ATR.
        """
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
        """Process tick and fire signal if MACD crossover aligns with ADX momentum."""
        close = float(candle["close"])
        high  = float(candle["high"])
        low   = float(candle["low"])
        
        self.candle_count += 1
        
        # ── 1. Update EMA200
        self.ema_200 = self._calc_ema(close, self.ema_200, self.ema_trend)
        
        # ── 2. Update MACD
        self.ema_fast = self._calc_ema(close, self.ema_fast, self.macd_fast)
        self.ema_slow = self._calc_ema(close, self.ema_slow, self.macd_slow)
        
        if self.candle_count >= self.macd_slow:
            self.macd_line = self.ema_fast - self.ema_slow
            self.signal_line = self._calc_ema(self.macd_line, self.signal_line, self.macd_signal)
            
            if self.signal_line is not None:
                self.prev_histogram = self.histogram
                self.histogram = self.macd_line - self.signal_line

        # ── 3. Update ADX & ATR Tracker
        if self.prev_close is not None:
            # Wilder's True Range
            tr = max(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
            
            # Directional Movement
            up_move = high - self.prev_high
            down_move = self.prev_low - low
            
            pdm = up_move if up_move > down_move and up_move > 0 else 0.0
            ndm = down_move if down_move > up_move and down_move > 0 else 0.0
            
            # Smoothing (RMA)
            if self.candle_count <= self.adx_period + 1:
                self.tr_list.append(tr)
                self.pdm_list.append(pdm)
                self.ndm_list.append(ndm)
                
                if len(self.tr_list) == self.adx_period:
                    self.smooth_tr = sum(self.tr_list)
                    self.smooth_pdm = sum(self.pdm_list)
                    self.smooth_ndm = sum(self.ndm_list)
                    self.last_atr = self.smooth_tr / self.adx_period
            else:
                self.smooth_tr = self.smooth_tr - (self.smooth_tr / self.adx_period) + tr
                self.smooth_pdm = self.smooth_pdm - (self.smooth_pdm / self.adx_period) + pdm
                self.smooth_ndm = self.smooth_ndm - (self.smooth_ndm / self.adx_period) + ndm
                
                self.last_atr = (self.last_atr * (self.adx_period - 1) + tr) / self.adx_period
                
                # ADX Calculation
                if self.smooth_tr > 0:
                    pdi = 100 * (self.smooth_pdm / self.smooth_tr)
                    ndi = 100 * (self.smooth_ndm / self.smooth_tr)
                    
                    dx = 100 * abs(pdi - ndi) / (pdi + ndi) if (pdi + ndi) > 0 else 0.0
                    
                    if len(self.dx_list) < self.adx_period:
                        self.dx_list.append(dx)
                        if len(self.dx_list) == self.adx_period:
                            self.adx = sum(self.dx_list) / self.adx_period
                    else:
                        self.adx = (self.adx * (self.adx_period - 1) + dx) / self.adx_period

        self.prev_high = high
        self.prev_low = low
        self.prev_close = close

        # ── 4. Signal Generation logic
        if self.candle_count < self.warmup_required:
            return Signal.HOLD

        final_signal = Signal.HOLD

        # Core Rules
        trend_is_up = close > self.ema_200
        trend_is_down = close < self.ema_200
        has_momentum = self.adx > self.adx_threshold
        
        # MACD Zero-Crossover trigger
        macd_buy_cross = (self.prev_histogram is not None) and (self.prev_histogram <= 0) and (self.histogram > 0)
        macd_sell_cross = (self.prev_histogram is not None) and (self.prev_histogram >= 0) and (self.histogram < 0)

        # Triggers
        if has_momentum and trend_is_up and macd_buy_cross:
            if self.prev_state != "LONG":
                final_signal = Signal.BUY
                logger.info(f"BUY SIGNAL | MACD Cross | ADX: {self.adx:.1f} > 25 | EMA200: {self.ema_200:.2f}")
                self.prev_state = "LONG"
                
        elif has_momentum and trend_is_down and macd_sell_cross:
            if self.prev_state != "SHORT":
                final_signal = Signal.SELL
                logger.info(f"SELL SIGNAL | MACD Cross | ADX: {self.adx:.1f} > 25 | EMA200: {self.ema_200:.2f}")
                self.prev_state = "SHORT"
                
        else:
            # Reset state if opposite cross happens (prevent spam, allow re-entry)
            if macd_sell_cross and self.prev_state == "LONG":
                self.prev_state = "NEUTRAL"
            elif macd_buy_cross and self.prev_state == "SHORT":
                self.prev_state = "NEUTRAL"

        return final_signal

    def get_state_str(self) -> str:
        h = f"{self.histogram:.1f}" if self.histogram else "--"
        ema = f"{self.ema_200:.1f}" if self.ema_200 else "--"
        a = f"{self.adx:.1f}" if self.adx > 0 else "--"
        return f" | ADX: {a} | MACD: {h} | EMA200: {ema}"

    def describe(self) -> dict:
        return {
            "strategy":       self.name,
            "macd_fast":      self.macd_fast,
            "macd_slow":      self.macd_slow,
            "adx_period":     self.adx_period,
            "adx_threshold":  self.adx_threshold,
            "ema_trend":      self.ema_trend,
            "atr_multiplier": self.atr_multiplier,
            "version":        "swing-macd-adx-ema-v1",
        }
