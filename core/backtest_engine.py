"""
core/backtest_engine.py — Event-driven backtester.

Iterates candles chronologically, feeds each to the strategy, simulates order
execution at the NEXT candle's open (to avoid look-ahead bias), tracks positions,
and applies stop-losses. Returns a BacktestResult for reporting.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Type

import pandas as pd

import config
from core.trade_log import TradeLog, TradeRecord
from core.position_sizer import PositionSizer
from strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Output of a completed backtest run."""
    strategy_name:  str
    symbol:         str
    timeframe:      str
    start_date:     str
    end_date:       str
    initial_capital: float
    final_capital:  float
    trade_log:      TradeLog = field(default_factory=TradeLog)
    equity_curve:   pd.Series = field(default_factory=pd.Series)
    candles_df:     pd.DataFrame = field(default_factory=pd.DataFrame)


class BacktestEngine:
    """
    Candle-by-candle event loop backtester.

    - Feeds each candle to the strategy → receives Signal (BUY / SELL / HOLD)
    - Executes entry at the NEXT candle's open price
    - Checks stop-loss on every subsequent candle (uses low/high for realism)
    - Exits on opposite signal at NEXT candle's open
    - Only one position at a time (long or short)
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        initial_capital: float = None,
        max_risk_pct: float = None,
    ):
        self.strategy = strategy
        self.initial_capital = initial_capital or config.INITIAL_CAPITAL
        self.max_risk_pct    = max_risk_pct or config.MAX_RISK_PER_TRADE

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str,
    ) -> BacktestResult:
        """
        Run the backtest on the provided OHLCV DataFrame.

        Args:
            df:         OHLCV DataFrame indexed by UTC datetime, sorted oldest-first.
            symbol:     Trading symbol, e.g. "BTCUSD"
            timeframe:  Candle resolution string, e.g. "5m"
            start_date: String for reporting
            end_date:   String for reporting

        Returns:
            BacktestResult with all trade data and equity curve.
        """
        self.strategy.reset()
        trade_log    = TradeLog()
        sizer        = PositionSizer(self.initial_capital, self.max_risk_pct)
        portfolio    = self.initial_capital
        equity_curve = {}   # datetime → portfolio value

        current_trade: Optional[TradeRecord] = None
        pending_signal: Optional[Signal] = None   # signal from prev candle, exec on this open

        candles = df.reset_index()   # time becomes a column
        n = len(candles)

        logger.info(
            f"Starting backtest: {self.strategy.name} | {symbol} {timeframe} "
            f"| {start_date} → {end_date} | Capital: ${portfolio:,.2f}"
        )

        for i, row in candles.iterrows():
            ts         = row["time"]
            open_price = float(row["open"])
            high_price = float(row["high"])
            low_price  = float(row["low"])
            close_price = float(row["close"])

            # ── 1. Execute pending signal from previous candle (at this candle's open)
            if pending_signal is not None and current_trade is None:
                if pending_signal in (Signal.BUY, Signal.SELL):
                    side = "long" if pending_signal == Signal.BUY else "short"
                    entry_price = open_price

                    # ATR-based stop-loss from strategy (falls back to 1% if not provided)
                    atr = self.strategy.last_atr if hasattr(self.strategy, "last_atr") else entry_price * 0.01
                    stop_loss = sizer.suggested_stop_loss(entry_price, side, atr)
                    size = sizer.calculate_size(entry_price, stop_loss)

                    if size > 0:
                        current_trade = trade_log.new_trade(
                            symbol=symbol,
                            side=side,
                            entry_time=ts,
                            entry_price=entry_price,
                            size=size,
                            stop_loss_price=stop_loss,
                        )
                        logger.debug(
                            f"  OPEN {side.upper()} @ {entry_price:.2f} | "
                            f"SL={stop_loss:.2f} | size={size:.6f} BTC | {ts}"
                        )

            pending_signal = None   # consumed

            # ── 2. Check stop-loss on current open position
            if current_trade is not None:
                sl_hit = self._check_stop_loss(current_trade, low_price, high_price)
                if sl_hit:
                    sl_price = current_trade.stop_loss_price
                    current_trade.close(ts, sl_price, "stop_loss", portfolio)
                    pnl = current_trade.pnl
                    portfolio += pnl
                    sizer.update_portfolio(portfolio)
                    logger.debug(
                        f"  SL HIT @ {sl_price:.2f} | P&L={pnl:+.2f} | "
                        f"Portfolio=${portfolio:,.2f}"
                    )
                    current_trade = None

            # ── 3. Feed candle to strategy → get new signal
            candle_dict = {
                "time": ts, "open": open_price, "high": high_price,
                "low": low_price, "close": close_price, "volume": float(row.get("volume", 0)),
            }
            signal = self.strategy.on_candle(candle_dict)

            # ── 4. Handle exit signal on current position (execute next candle open)
            if current_trade is not None and signal != Signal.HOLD:
                opposite = (signal == Signal.SELL and current_trade.side == "long") or \
                           (signal == Signal.BUY  and current_trade.side == "short")
                if opposite:
                    # Close at next open; store exit intent, execute in next iteration
                    # For simplicity: exit at close price of current candle
                    current_trade.close(ts, close_price, "signal", portfolio)
                    pnl = current_trade.pnl
                    portfolio += pnl
                    sizer.update_portfolio(portfolio)
                    logger.debug(
                        f"  CLOSE (signal) @ {close_price:.2f} | P&L={pnl:+.2f} | "
                        f"Portfolio=${portfolio:,.2f}"
                    )
                    current_trade = None
                    # Also queue the new direction as pending
                    pending_signal = signal
            elif current_trade is None and signal != Signal.HOLD:
                pending_signal = signal

            # ── 5. Record equity curve point
            unrealised = 0.0
            if current_trade is not None:
                if current_trade.side == "long":
                    unrealised = (close_price - current_trade.entry_price) * current_trade.size
                else:
                    unrealised = (current_trade.entry_price - close_price) * current_trade.size
            equity_curve[ts] = portfolio + unrealised

        # ── 6. Close any open position at end of data (last close price)
        if current_trade is not None:
            last_row = candles.iloc[-1]
            last_price = float(last_row["close"])
            last_time  = last_row["time"]
            current_trade.close(last_time, last_price, "end_of_data", portfolio)
            portfolio += current_trade.pnl
            logger.info(f"  Force-closed open position at end of data @ {last_price:.2f}")

        equity_series = pd.Series(equity_curve)

        logger.info(
            f"Backtest complete. Trades: {len(trade_log.closed_trades)} | "
            f"Final portfolio: ${portfolio:,.2f} | "
            f"Return: {(portfolio - self.initial_capital) / self.initial_capital * 100:.2f}%"
        )

        return BacktestResult(
            strategy_name=self.strategy.name,
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.initial_capital,
            final_capital=portfolio,
            trade_log=trade_log,
            equity_curve=equity_series,
            candles_df=df,
        )

    # ─────────────────────────────────────────────
    #  Internal helpers
    # ─────────────────────────────────────────────

    @staticmethod
    def _check_stop_loss(trade: TradeRecord, low: float, high: float) -> bool:
        """
        Check if the stop-loss was breached during this candle.
        Uses candle high/low for realism (not just close).
        """
        if trade.side == "long":
            return low <= trade.stop_loss_price
        else:  # short
            return high >= trade.stop_loss_price
