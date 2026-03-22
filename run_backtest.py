"""
run_backtest.py — CLI entry point for running a backtest.

Usage examples:
    python run_backtest.py
    python run_backtest.py --strategy bollinger_bands --timeframe 5m
    python run_backtest.py --timeframe 15m --start 2024-06-01 --end 2025-03-21
    python run_backtest.py --strategy bollinger_bands --capital 50000 --risk 0.5

All parameters have sensible defaults from config.py.
"""
import argparse
import importlib
import logging
import os
import sys

# Ensure project root is on path when run directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from core.data_fetcher import DataFetcher
from core.backtest_engine import BacktestEngine
from reports.html_reporter import generate_report

# ─────────────────────────────────────────────
#  Logging setup
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
import pytz
# Configure logging to use IST
logging.Formatter.converter = lambda *args: datetime.now(tz=pytz.timezone("Asia/Kolkata")).timetuple()
logger = logging.getLogger("run_backtest")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run a backtest on Delta Exchange India historical data."
    )
    parser.add_argument(
        "--strategy", "-s",
        default="bollinger_bands",
        help="Strategy module name (e.g. bollinger_bands). Default: bollinger_bands",
    )
    parser.add_argument(
        "--symbol",
        default=config.SYMBOL,
        help=f"Trading symbol. Default: {config.SYMBOL}",
    )
    parser.add_argument(
        "--timeframe", "-t",
        default=config.TIMEFRAME,
        help=f"Candle resolution (e.g. 5m, 15m, 1h). Default: {config.TIMEFRAME}",
    )
    parser.add_argument(
        "--start",
        default=config.BACKTEST_START,
        help=f"Start date YYYY-MM-DD. Default: {config.BACKTEST_START}",
    )
    parser.add_argument(
        "--end",
        default=config.BACKTEST_END,
        help=f"End date YYYY-MM-DD. Default: {config.BACKTEST_END}",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=config.INITIAL_CAPITAL,
        help=f"Initial capital in USD. Default: {config.INITIAL_CAPITAL}",
    )
    parser.add_argument(
        "--risk",
        type=float,
        default=config.MAX_RISK_PER_TRADE * 100,
        help=f"Max risk per trade in %%. Default: {config.MAX_RISK_PER_TRADE * 100}",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass local OHLCV data cache and re-fetch from API.",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Skip generating the HTML report.",
    )
    return parser.parse_args()


def load_strategy(name: str):
    """Dynamically import and instantiate a strategy by module name."""
    try:
        module = importlib.import_module(f"strategies.{name}")
    except ModuleNotFoundError:
        logger.error(f"Strategy module 'strategies/{name}.py' not found.")
        sys.exit(1)

    class_name = "".join(part.title() for part in name.split("_")) + "Strategy"
    cls = getattr(module, class_name, None)
    if cls is None:
        logger.error(
            f"Class '{class_name}' not found in strategies/{name}.py. "
            "Convention: class must be CamelCase + 'Strategy' suffix."
        )
        sys.exit(1)
    return cls()


def main():
    args = parse_args()

    logger.info("=" * 60)
    logger.info("  Delta Antigravity — Backtest Runner")
    logger.info("=" * 60)
    logger.info(f"  Strategy  : {args.strategy}")
    logger.info(f"  Symbol    : {args.symbol}")
    logger.info(f"  Timeframe : {args.timeframe}")
    logger.info(f"  Range     : {args.start} → {args.end} (IST)")
    logger.info(f"  Capital   : ${args.capital:,.2f}")
    logger.info(f"  Risk/trade: {args.risk:.2f}%")
    logger.info(f"  Cache     : {'OFF' if args.no_cache else 'ON'}")
    logger.info("=" * 60)

    # ── Fetch data ──────────────────────────────
    logger.info("Step 1/3 — Fetching OHLCV data…")
    fetcher = DataFetcher()
    df = fetcher.fetch(
        symbol=args.symbol,
        resolution=args.timeframe,
        start_date=args.start,
        end_date=args.end,
        use_cache=not args.no_cache,
    )

    if df.empty:
        logger.error("No data returned. Check symbol, timeframe, and date range.")
        sys.exit(1)

    logger.info(f"  → {len(df):,} candles loaded ({args.start} to {args.end})")

    # ── Run backtest ────────────────────────────
    logger.info("Step 2/3 — Running backtest…")
    strategy = load_strategy(args.strategy)
    engine   = BacktestEngine(
        strategy=strategy,
        initial_capital=args.capital,
        max_risk_pct=args.risk / 100,
    )
    result = engine.run(
        df=df,
        symbol=args.symbol,
        timeframe=args.timeframe,
        start_date=args.start,
        end_date=args.end,
    )

    # ── Print summary ───────────────────────────
    trades = result.trade_log.closed_trades
    final  = result.final_capital
    ret    = (final - args.capital) / args.capital * 100

    print("\n" + "=" * 60)
    print("  BACKTEST RESULTS")
    print("=" * 60)
    print(f"  Total Trades    : {len(trades)}")
    print(f"  Initial Capital : ${args.capital:,.2f}")
    print(f"  Final Capital   : ${final:,.2f}")
    print(f"  Total Return    : {ret:+.2f}%")
    if trades:
        winners  = [t for t in trades if t.pnl > 0]
        win_rate = len(winners) / len(trades) * 100
        print(f"  Win Rate        : {win_rate:.1f}%")
    print("=" * 60 + "\n")

    # ── Generate report ─────────────────────────
    if not args.no_report:
        logger.info("Step 3/3 — Generating HTML report…")
        report_path = generate_report(result)
        print(f"  📄 Report saved → {report_path}")
        print(f"     Open in your browser to view the full report.\n")
    else:
        logger.info("Step 3/3 — Skipping report (--no-report flag set).")

    return result


if __name__ == "__main__":
    main()
