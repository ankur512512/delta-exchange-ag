"""
strategies/base_strategy.py — Abstract base class for all trading strategies.

To create a new strategy:
  1. Create a new file in the strategies/ folder
  2. Subclass BaseStrategy
  3. Implement on_candle() and reset()
  4. Pass an instance to BacktestEngine

Example:
    from strategies.base_strategy import BaseStrategy, Signal

    class MyStrategy(BaseStrategy):
        name = "my_strategy"

        def reset(self):
            self._prices = []

        def on_candle(self, candle: dict) -> Signal:
            self._prices.append(candle["close"])
            if len(self._prices) < 20:
                return Signal.HOLD
            # ... your logic here ...
            return Signal.BUY
"""
from abc import ABC, abstractmethod
from enum import Enum


class Signal(Enum):
    """Trading signal returned by a strategy on each candle."""
    BUY  = "buy"
    SELL = "sell"
    HOLD = "hold"


class BaseStrategy(ABC):
    """
    Abstract base class for all strategies.

    The backtester calls on_candle() for every OHLCV candle in sequence.
    Internal indicator state (rolling windows, etc.) must be maintained
    inside the strategy itself.

    Attributes:
        name (str): Unique strategy identifier, used in reports and filenames.
                    Override this as a class attribute in every subclass.
    """

    name: str = "base_strategy"

    @abstractmethod
    def on_candle(self, candle: dict) -> Signal:
        """
        Process a new OHLCV candle and return a trading signal.

        Args:
            candle: dict with keys:
                - time:   pandas Timestamp (UTC)
                - open:   float
                - high:   float
                - low:    float
                - close:  float
                - volume: float

        Returns:
            Signal.BUY  — open a long position (or close short and go long)
            Signal.SELL — open a short position (or close long and go short)
            Signal.HOLD — do nothing
        """
        ...

    @abstractmethod
    def reset(self):
        """
        Reset all internal state. Called by the backtester before each run
        to ensure a clean slate when testing the same strategy multiple times.
        """
        ...

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"<Strategy: {self.name}>"
