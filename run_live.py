"""
run_live.py — Pro Live Trading Runner for Delta Exchange India.

⚠️  WARNING: This script executes REAL TRADES with REAL MONEY when MODE=LIVE.
Always test with --dry-run first to verify signals and sizing logic.

Key Features:
- Real-time position tracking (syncs with API daily/per-loop).
- IST-localized logging.
- Respects Delta Exchange rate limits.
- Strategic 'Falling Knife' protection included from bollinger_bands strategy.
"""
import argparse
import importlib
import logging
import os
import sys
import time
from datetime import datetime, timedelta
import pytz

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from core.delta_client import DeltaClient
from core.data_fetcher import DataFetcher, RESOLUTION_SECONDS
from core.position_sizer import PositionSizer
from strategies.base_strategy import Signal

# ─────────────────────────────────────────────
#  Logging Configuration (IST)
# ─────────────────────────────────────────────
ist_tz = pytz.timezone("Asia/Kolkata")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.Formatter.converter = lambda *args: datetime.now(tz=ist_tz).timetuple()
logger = logging.getLogger("LIVE_TRADER")

# Number of candles to fetch for indicator warmup
WARMUP_CANDLES = 100 


def parse_args():
    parser = argparse.ArgumentParser(description="Live trading runner for Delta Exchange.")
    parser.add_argument("--strategy", "-s", default="bollinger_bands")
    parser.add_argument("--symbol",   default=config.SYMBOL)
    parser.add_argument("--timeframe", "-t", default=config.TIMEFRAME)
    parser.add_argument("--dry-run",  action="store_true", help="Monitor and log but DO NOT place orders.")
    parser.add_argument("--risk",     type=float, default=config.MAX_RISK_PER_TRADE * 100, help="Risk % per trade")
    return parser.parse_args()


def main():
    args = parse_args()
    mode_label = "DRY-RUN" if args.dry_run else config.MODE
    
    logger.info("="*60)
    logger.info(f" STARTING LIVE BOT | Strategy: {args.strategy} | Mode: {mode_label}")
    logger.info(f" Symbol: {args.symbol} | Timeframe: {args.timeframe} | Risk: {args.risk}%")
    logger.info("="*60)

    client = DeltaClient()
    fetcher = DataFetcher(client)
    
    # Load strategy
    try:
        module = importlib.import_module(f"strategies.{args.strategy}")
        class_name = "".join(p.title() for p in args.strategy.split("_")) + "Strategy"
        strategy_cls = getattr(module, class_name)
        strategy = strategy_cls()
    except Exception as e:
        logger.error(f"Failed to load strategy '{args.strategy}': {e}")
        return

    candle_secs = RESOLUTION_SECONDS.get(args.timeframe, 300)

    try:
        while True:
            now_ist = datetime.now(ist_tz)
            
            # ── 1. Sync Portfolio & Position ────────────────
            try:
                if config.MODE == "LIVE" and not args.dry_run:
                    balance = client.get_wallet_balance(asset="USD")
                    pos_data = client.get_position(args.symbol)
                    current_size = float(pos_data.get("size", 0))
                else:
                    balance = config.INITIAL_CAPITAL
                    current_size = 0.0
                
                pos_label = "NONE"
                if current_size > 0: pos_label = f"LONG ({current_size})"
                elif current_size < 0: pos_label = f"SHORT ({abs(current_size)})"
                
                logger.info(f"SYNC | Wallet: ${balance:,.2f} | Position: {pos_label}")
            except Exception as e:
                logger.error(f"Sync error (will retry): {e}")
                time.sleep(10)
                continue

            # ── 2. Fetch Fresh Data ─────────────────────────
            # Use tomorrow's date for end_date to ensure we catch all of today's latest candles
            now_utc = datetime.now(pytz.UTC)
            end_date = (now_utc + timedelta(days=1)).strftime("%Y-%m-%d")
            start_time = now_utc - timedelta(seconds=WARMUP_CANDLES * candle_secs)
            start_date = start_time.strftime("%Y-%m-%d")

            try:
                df = fetcher.fetch(
                    symbol=args.symbol,
                    resolution=args.timeframe,
                    start_date=start_date,
                    end_date=end_date,
                    use_cache=False
                )
            except Exception as e:
                logger.error(f"Data error: {e}")
                time.sleep(30)
                continue

            if df.empty:
                logger.warning("No candles returned. Retrying in 30s...")
                time.sleep(30)
                continue

            # ── 3. Run Strategy Logic ───────────────────────
            strategy.reset()
            last_signal = Signal.HOLD
            for _, row in df.reset_index().iterrows():
                candle = {
                    "time": row["time"], "open": float(row["open"]),
                    "high": float(row["high"]), "low": float(row["low"]),
                    "close": float(row["close"]), "volume": float(row.get("volume", 0))
                }
                last_signal = strategy.on_candle(candle)

            current_price = float(df.iloc[-1]["close"])
            logger.info(f"MARKET | {args.symbol} @ ${current_price:,.2f} | Signal: {last_signal.value}")

            # ── 4. Execute Trades ───────────────────────────
            sizer = PositionSizer(balance, args.risk / 100)
            atr = strategy.last_atr if hasattr(strategy, "last_atr") and strategy.last_atr > 0 else current_price * 0.01
            
            # Check for entry signals
            if last_signal == Signal.BUY and current_size <= 0:
                sl_price = sizer.suggested_stop_loss(current_price, "long", atr)
                size = sizer.calculate_size(current_price, sl_price)
                
                logger.info(f"🚀 BUY SIGNAL DETECTED | Size: {size:.4f} | SL: {sl_price:.2f}")
                if config.MODE == "LIVE" and not args.dry_run:
                    client.place_order(args.symbol, "buy", size, "market_order", stop_loss=sl_price)
                    _log_live_trade(args.symbol, "BUY", size, current_price, sl_price)
                else:
                    logger.info("[DRY-RUN] No real order placed.")

            elif last_signal == Signal.SELL and current_size >= 0:
                sl_price = sizer.suggested_stop_loss(current_price, "short", atr)
                size = sizer.calculate_size(current_price, sl_price)
                
                logger.info(f"🚀 SELL SIGNAL DETECTED | Size: {size:.4f} | SL: {sl_price:.2f}")
                if config.MODE == "LIVE" and not args.dry_run:
                    client.place_order(args.symbol, "sell", size, "market_order", stop_loss=sl_price)
                    _log_live_trade(args.symbol, "SELL", size, current_price, sl_price)
                else:
                    logger.info("[DRY-RUN] No real order placed.")

            # ── 5. Wait for Next Candle ─────────────────────
            # Align with the clock (e.g. if 5m, wait until 00:00, 05:00, etc.)
            seconds_into_candle = now_ist.minute % int(args.timeframe.replace("m", "")) * 60 + now_ist.second
            wait_time = max(candle_secs - seconds_into_candle + 2, 10) # +2s for buffer
            
            next_run = (datetime.now(ist_tz) + timedelta(seconds=wait_time)).strftime("%H:%M:%S")
            logger.info(f"WAIT | Next check at {next_run} IST...")
            time.sleep(wait_time)

    except KeyboardInterrupt:
        logger.info("\nBot stopped manually. Safe trading!")

def _log_live_trade(symbol, side, size, price, sl):
    """Save the trade to a CSV file for auditing."""
    import csv
    log_dir = "data"
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "live_trades.csv")
    
    file_exists = os.path.exists(log_path)
    timestamp = datetime.now(ist_tz).strftime("%Y-%m-%d %H:%M:%S")
    
    with open(log_path, mode="a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "symbol", "side", "size", "price", "stop_loss"])
        writer.writerow([timestamp, symbol, side, size, price, sl])
    logger.info(f"Logged {side} trade to {log_path}")


if __name__ == "__main__":
    main()
