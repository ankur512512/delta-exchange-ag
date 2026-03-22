"""
core/trade_log.py — Trade record model and logger.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


@dataclass
class TradeRecord:
    """Represents a single completed trade (entry → exit)."""

    trade_id:       int
    symbol:         str
    side:           str          # "long" or "short"
    entry_time:     datetime
    entry_price:    float
    size:           float        # number of contracts / BTC size
    stop_loss_price: float

    exit_time:      Optional[datetime] = None
    exit_price:     Optional[float]    = None
    exit_reason:    Optional[str]      = None   # "stop_loss" | "signal" | "end_of_data"

    pnl:            float = 0.0          # absolute USD P&L
    pnl_pct:        float = 0.0          # P&L as % of position value at entry
    portfolio_value: float = 0.0         # portfolio value after this trade closes

    def close(
        self,
        exit_time: datetime,
        exit_price: float,
        exit_reason: str,
        portfolio_value: float,
    ):
        """Mark the trade as closed and compute P&L."""
        self.exit_time  = exit_time
        self.exit_price = exit_price
        self.exit_reason = exit_reason
        self.portfolio_value = portfolio_value

        if self.side == "long":
            self.pnl = (exit_price - self.entry_price) * self.size
        else:  # short
            self.pnl = (self.entry_price - exit_price) * self.size

        position_value = self.entry_price * self.size
        self.pnl_pct = (self.pnl / position_value * 100) if position_value > 0 else 0.0

    @property
    def holding_period_hours(self) -> Optional[float]:
        """Duration of the trade in hours."""
        if self.exit_time and self.entry_time:
            delta = self.exit_time - self.entry_time
            return delta.total_seconds() / 3600
        return None

    def to_dict(self) -> dict:
        import pandas as pd
        def format_dt(dt):
            if dt is None: return None
            # If naive, localize as UTC first, then to IST. If aware, just convert.
            ts = pd.Timestamp(dt)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            return ts.tz_convert("Asia/Kolkata").strftime("%Y-%m-%d %H:%M:%S")

        return {
            "trade_id":        self.trade_id,
            "symbol":          self.symbol,
            "side":            self.side,
            "entry_time":      format_dt(self.entry_time),
            "entry_price":     self.entry_price,
            "size":            self.size,
            "stop_loss_price": self.stop_loss_price,
            "exit_time":       format_dt(self.exit_time),
            "exit_price":      self.exit_price,
            "exit_reason":     self.exit_reason,
            "pnl":             round(self.pnl, 4),
            "pnl_pct":         round(self.pnl_pct, 4),
            "portfolio_value": round(self.portfolio_value, 2),
            "holding_hours":   round(self.holding_period_hours, 2) if self.holding_period_hours else None,
        }


class TradeLog:
    """Accumulates trade records during a backtest run."""

    def __init__(self):
        self._trades: List[TradeRecord] = []
        self._next_id = 1

    def new_trade(self, **kwargs) -> TradeRecord:
        """Create and register a new trade."""
        trade = TradeRecord(trade_id=self._next_id, **kwargs)
        self._trades.append(trade)
        self._next_id += 1
        return trade

    @property
    def trades(self) -> List[TradeRecord]:
        """All trades (open and closed)."""
        return self._trades

    @property
    def closed_trades(self) -> List[TradeRecord]:
        """Only fully closed trades."""
        return [t for t in self._trades if t.exit_time is not None]

    def to_dataframe(self):
        """Convert closed trades to a pandas DataFrame."""
        import pandas as pd
        if not self.closed_trades:
            return pd.DataFrame()
        df_res = pd.DataFrame([t.to_dict() for t in self.closed_trades])
        # Ensure strings don't get converted back to UTC by pandas inference
        if "entry_time" in df_res.columns:
            df_res["entry_time"] = df_res["entry_time"].astype(str)
        if "exit_time" in df_res.columns:
            df_res["exit_time"] = df_res["exit_time"].astype(str)
        return df_res
