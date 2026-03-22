"""
run_live.py — Live trading runner for Delta Exchange India.

⚠️  WARNING: This will place REAL orders with REAL money when MODE=LIVE.
    Set MODE=BACKTEST in your .env to simulate without executing trades.

Usage:
    python run_live.py --strategy bollinger_bands --timeframe 5m
    python run_live.py --strategy bollinger_bands --timeframe 15m --symbol ETHUSD

The live runner:
  1. Fetches the latest candles (last N candles needed for indicator warmup)
  2. Computes the current strategy signal
  3. If actionable: checks current position and places/modifies orders accordingly
  4. Loops on a schedule matching the chosen timeframe
"""
import argparse
import importlib
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from core.delta_client import DeltaClient
from core.data_fetcher import DataFetcher, RESOLUTION_SECONDS
from core.position_sizer import PositionSizer
from strategies.base_strategy import Signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
import pytz
# Configure logging to use IST
logging.Formatter.converter = lambda *args: datetime.now(tz=pytz.timezone("Asia/Kolkata")).timetuple()
logger = logging.getLogger("run_live")

# Warmup candles needed for indicators (BB20 + RSI14 + ATR14 + buffer)
WARMUP_CANDLES = 60


def parse_args():
    parser = argparse.ArgumentParser(description="Live trading runner for Delta Exchange India.")
    parser.add_argument("--strategy", "-s", default="bollinger_bands")
    parser.add_argument("--symbol",   default=config.SYMBOL)
    parser.add_argument("--timeframe", "-t", default=config.TIMEFRAME)
    parser.add_argument("--capital",  type=float, default=None,
                        help="Override initial capital for position sizing (default: read from wallet)")
    parser.add_argument("--risk",     type=float, default=config.MAX_RISK_PER_TRADE * 100,
                        help="Max risk per trade in %%")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Print intended actions but do NOT place orders (safe for testing)")
    return parser.parse_args()


def load_strategy(name: str):
    module = importlib.import_module(f"strategies.{name}")
    class_name = "".join(p.title() for p in name.split("_")) + "Strategy"
    cls = getattr(module, class_name)
    return cls()


def main():
    args = parse_args()

    mode_label = "DRY-RUN" if args.dry_run else config.MODE
    logger.info("=" * 60)
    logger.info(f"  Delta Antigravity — Live Runner ({mode_label})")
    logger.info("=" * 60)

    if config.MODE == "LIVE" and not args.dry_run:
        logger.warning("⚠️  LIVE MODE ACTIVE — Real orders will be placed!")
        if not config.API_KEY or not config.API_SECRET:
            logger.error("API_KEY and API_SECRET must be set in .env for LIVE mode.")
            sys.exit(1)

    client   = DeltaClient()
    fetcher  = DataFetcher(client)
    strategy = load_strategy(args.strategy)

    # Get portfolio value for sizing
    if args.capital:
        portfolio_value = args.capital
    elif config.MODE == "LIVE" and not args.dry_run:
        portfolio_value = client.get_wallet_balance(asset="USD")
        logger.info(f"Wallet balance: ${portfolio_value:,.2f} USD")
    else:
        portfolio_value = config.INITIAL_CAPITAL
        logger.info(f"Using configured initial capital: ${portfolio_value:,.2f} USD")

    sizer       = PositionSizer(portfolio_value, args.risk / 100)
    candle_secs = RESOLUTION_SECONDS.get(args.timeframe, 300)

    logger.info(f"Strategy: {args.strategy} | {args.symbol} {args.timeframe}")
    logger.info(f"Press Ctrl+C to stop.\n")

    open_position = None   # Track our simulated/real position

    try:
        while True:
            # Main cycle uses IST for easier tracking by USER
            ist = pytz.timezone("Asia/Kolkata")
            loop_start_ist = datetime.now(ist)
            loop_start_utc = loop_start_ist.astimezone(pytz.UTC)

            # ── Fetch recent candles for warmup ──────────
            end_ts   = int(loop_start_utc.timestamp())
            start_ts = end_ts - (WARMUP_CANDLES * candle_secs)
            end_date   = loop_start_utc.strftime("%Y-%m-%d")
            # Compute start date
            start_time = loop_start_utc - timedelta(seconds=WARMUP_CANDLES * candle_secs)
            start_date = start_time.strftime("%Y-%m-%d")

            try:
                df = fetcher.fetch(
                    symbol=args.symbol,
                    resolution=args.timeframe,
                    start_date=start_date,
                    end_date=end_date,
                    use_cache=False,  # Always fresh data in live
                )
            except Exception as e:
                logger.error(f"Data fetch error: {e}. Retrying next cycle…")
                time.sleep(candle_secs)
                continue

            if df.empty or len(df) < 5:
                logger.warning("Insufficient candles returned. Waiting…")
                time.sleep(candle_secs)
                continue

            # ── Feed candles to strategy ─────────────────
            strategy.reset()
            last_signal = Signal.HOLD
            for _, row in df.reset_index().iterrows():
                candle = {
                    "time":   row["time"],
                    "open":   float(row["open"]),
                    "high":   float(row["high"]),
                    "low":    float(row["low"]),
                    "close":  float(row["close"]),
                    "volume": float(row.get("volume", 0)),
                }
                last_signal = strategy.on_candle(candle)

            last_candle = df.iloc[-1]
            current_price = float(last_candle["close"])
            logger.info(
                f"[{loop_start_ist.strftime('%H:%M:%S')}] "
                f"{args.symbol} @ ${current_price:,.2f} | Signal: {last_signal.value.upper()}"
            )

            # ── Act on signal ─────────────────────────────
            atr        = strategy.last_atr if hasattr(strategy, "last_atr") else current_price * 0.01
            action_msg = None

            if last_signal == Signal.BUY and open_position != "long":
                stop_loss = sizer.suggested_stop_loss(current_price, "long", atr)
                size      = sizer.calculate_size(current_price, stop_loss)
                action_msg = (
                    f"ACTION: BUY {size:.6f} {args.symbol} @ ~{current_price:.2f} "
                    f"| SL={stop_loss:.2f}"
                )
                if config.MODE == "LIVE" and not args.dry_run:
                    resp = client.place_order(
                        symbol=args.symbol, side="buy", size=size,
                        order_type="market_order", stop_loss=stop_loss
                    )
                    logger.info(f"Order response: {resp}")
                open_position = "long"

            elif last_signal == Signal.SELL and open_position != "short":
                stop_loss = sizer.suggested_stop_loss(current_price, "short", atr)
                size      = sizer.calculate_size(current_price, stop_loss)
                action_msg = (
                    f"ACTION: SELL {size:.6f} {args.symbol} @ ~{current_price:.2f} "
                    f"| SL={stop_loss:.2f}"
                )
                if config.MODE == "LIVE" and not args.dry_run:
                    resp = client.place_order(
                        symbol=args.symbol, side="sell", size=size,
                        order_type="market_order", stop_loss=stop_loss
                    )
                    logger.info(f"Order response: {resp}")
                open_position = "short"

            if action_msg:
                prefix = "[DRY-RUN] " if (args.dry_run or config.MODE != "LIVE") else "[LIVE] "
                logger.info(prefix + action_msg)

            # ── Wait for next candle close ────────────────
            elapsed = (datetime.now(ist) - loop_start_ist).total_seconds()
            sleep_time = max(candle_secs - elapsed, 5)
            logger.debug(f"Sleeping {sleep_time:.0f}s until next candle…")
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("\nStopped by user. Goodbye!")


if __name__ == "__main__":
    main()
