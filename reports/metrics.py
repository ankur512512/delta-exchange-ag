"""
reports/metrics.py — Compute performance statistics from backtest results.
"""
import math
import logging
from typing import List, Dict, Any

import pandas as pd

from core.trade_log import TradeRecord

logger = logging.getLogger(__name__)


def compute_metrics(
    trades: List[TradeRecord],
    equity_curve: pd.Series,
    initial_capital: float,
    timeframe: str = "5m",
) -> Dict[str, Any]:
    """
    Compute the full suite of backtest performance metrics.

    Args:
        trades:          List of closed TradeRecord objects
        equity_curve:    pd.Series (datetime index → portfolio value)
        initial_capital: Starting portfolio value in USD
        timeframe:       Candle timeframe string (used to annualise Sharpe)

    Returns:
        Dict of metric name → value (all monetary values in USD)
    """
    if not trades:
        return _empty_metrics(initial_capital)

    # ── Core P&L ──────────────────────────────────
    pnls         = [t.pnl for t in trades]
    total_pnl    = sum(pnls)
    final_value  = equity_curve.iloc[-1] if not equity_curve.empty else initial_capital
    total_return = (final_value - initial_capital) / initial_capital * 100

    # ── Win Rate ──────────────────────────────────
    winners      = [p for p in pnls if p > 0]
    losers       = [p for p in pnls if p < 0]
    win_rate     = len(winners) / len(pnls) * 100 if pnls else 0.0

    # ── Profit Factor ─────────────────────────────
    gross_profit = sum(winners)
    gross_loss   = abs(sum(losers))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # ── Average Trade ─────────────────────────────
    avg_trade_pnl    = total_pnl / len(pnls)
    avg_winner       = sum(winners) / len(winners) if winners else 0.0
    avg_loser        = sum(losers) / len(losers) if losers else 0.0

    # ── Max Drawdown ──────────────────────────────
    max_dd, max_dd_pct, max_dd_duration = _max_drawdown(equity_curve)

    # ── Sharpe Ratio ──────────────────────────────
    sharpe = _sharpe_ratio(equity_curve, timeframe)

    # ── Holding Period ────────────────────────────
    holding_hours = [t.holding_period_hours for t in trades if t.holding_period_hours]
    avg_holding_h = sum(holding_hours) / len(holding_hours) if holding_hours else 0.0

    # ── Annualised Return (CAGR approximation) ────
    duration_days = _duration_days(equity_curve)
    annualised_return = _annualised_return(total_return, duration_days)

    # ── Consecutive win/loss streaks ───────────────
    max_consec_wins, max_consec_losses = _streaks(pnls)

    return {
        # Summary
        "total_trades":        len(trades),
        "winning_trades":      len(winners),
        "losing_trades":       len(losers),
        "win_rate_pct":        round(win_rate, 2),

        # P&L
        "initial_capital":     round(initial_capital, 2),
        "final_capital":       round(final_value, 2),
        "total_pnl":           round(total_pnl, 2),
        "total_return_pct":    round(total_return, 2),
        "annualised_return_pct": round(annualised_return, 2),

        # Per-trade stats
        "avg_trade_pnl":       round(avg_trade_pnl, 2),
        "avg_winner":          round(avg_winner, 2),
        "avg_loser":           round(avg_loser, 2),
        "profit_factor":       round(profit_factor, 3) if profit_factor != float("inf") else "∞",
        "avg_holding_hours":   round(avg_holding_h, 1),

        # Risk
        "max_drawdown_usd":    round(max_dd, 2),
        "max_drawdown_pct":    round(max_dd_pct, 2),
        "max_drawdown_duration_candles": max_dd_duration,
        "sharpe_ratio":        round(sharpe, 3),

        # Streaks
        "max_consecutive_wins":   max_consec_wins,
        "max_consecutive_losses": max_consec_losses,
    }


# ─────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────

def _max_drawdown(equity: pd.Series):
    """Compute max drawdown in USD, %, and duration in candles."""
    if equity.empty or len(equity) < 2:
        return 0.0, 0.0, 0

    peak = equity.iloc[0]
    max_dd = 0.0
    max_dd_pct = 0.0
    current_dd_start = 0
    max_dd_duration = 0
    current_start_idx = 0

    for i, val in enumerate(equity):
        if val >= peak:
            peak = val
            current_start_idx = i
        dd = peak - val
        dd_pct = dd / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct
            max_dd_duration = i - current_start_idx

    return max_dd, max_dd_pct, max_dd_duration


def _sharpe_ratio(equity: pd.Series, timeframe: str, risk_free: float = 0.0) -> float:
    """
    Compute annualised Sharpe ratio from equity curve.
    Converts per-candle returns to annual using timeframe-specific factor.
    """
    if equity.empty or len(equity) < 2:
        return 0.0

    # Candles per year mapping
    candles_per_year = {
        "1m": 525_600, "3m": 175_200, "5m": 105_120,
        "15m": 35_040,  "30m": 17_520, "1h": 8_760,
        "2h": 4_380,    "4h": 2_190,   "6h": 1_460,
        "1d": 365,      "1w": 52,
    }
    annual_factor = candles_per_year.get(timeframe, 105_120)

    returns = equity.pct_change().dropna()
    if returns.std() == 0:
        return 0.0

    excess_returns = returns - (risk_free / annual_factor)
    sharpe = (excess_returns.mean() / excess_returns.std()) * math.sqrt(annual_factor)
    return sharpe


def _annualised_return(total_return_pct: float, duration_days: float) -> float:
    """Compute CAGR-style annualised return."""
    if duration_days <= 0:
        return 0.0
    multiplier = (1 + total_return_pct / 100) ** (365 / duration_days) - 1
    return multiplier * 100


def _duration_days(equity: pd.Series) -> float:
    """Compute total backtest duration in days."""
    if equity.empty or len(equity) < 2:
        return 1.0
    try:
        delta = equity.index[-1] - equity.index[0]
        return max(delta.total_seconds() / 86400, 1.0)
    except Exception:
        return 365.0


def _streaks(pnls: list):
    """Compute max consecutive wins and losses."""
    max_wins = max_losses = cur_wins = cur_losses = 0
    for p in pnls:
        if p > 0:
            cur_wins += 1
            cur_losses = 0
        else:
            cur_losses += 1
            cur_wins = 0
        max_wins   = max(max_wins, cur_wins)
        max_losses = max(max_losses, cur_losses)
    return max_wins, max_losses


def _empty_metrics(initial_capital: float) -> dict:
    return {
        "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
        "win_rate_pct": 0, "initial_capital": initial_capital,
        "final_capital": initial_capital, "total_pnl": 0,
        "total_return_pct": 0, "annualised_return_pct": 0,
        "avg_trade_pnl": 0, "avg_winner": 0, "avg_loser": 0,
        "profit_factor": 0, "avg_holding_hours": 0,
        "max_drawdown_usd": 0, "max_drawdown_pct": 0,
        "max_drawdown_duration_candles": 0, "sharpe_ratio": 0,
        "max_consecutive_wins": 0, "max_consecutive_losses": 0,
    }
