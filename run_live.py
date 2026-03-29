"""
run_live.py — Pro Live Trading & DEMO Runner for Delta Exchange India.

⚠️  WARNING: This script records trades in a journal for DEMO mode. 
If MODE=LIVE, it executes REAL TRADES with REAL MONEY.

Features:
- REAL-TIME JSON State serialization (survives sudden system reboots).
- Automatic alignment with API actual positions.
- Generates fully featured, dashboard-friendly backtest-style CSV logs.
- Dedicated DEMO mode using INR balance logic.
"""
import argparse
import importlib
import logging
import os
import sys
import time
import json
import csv
from datetime import datetime, timedelta
import pytz
import pandas as pd

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from core.delta_client import DeltaClient
from core.data_fetcher import DataFetcher, RESOLUTION_SECONDS
from core.position_sizer import PositionSizer
from strategies.base_strategy import Signal
from core.trade_log import TradeRecord

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

WARMUP_CANDLES = 1000 

def parse_args():
    parser = argparse.ArgumentParser(description="Live trading runner for Delta Exchange.")
    parser.add_argument("--strategy", "-s", default="bollinger_bands")
    parser.add_argument("--symbol",   default=config.SYMBOL)
    parser.add_argument("--timeframe", "-t", default=config.TIMEFRAME)
    parser.add_argument("--dry-run",  action="store_true", help="Force DEMO mode regardless of config.")
    parser.add_argument("--risk",     type=float, default=config.MAX_RISK_PER_TRADE * 100, help="Risk % per trade")
    return parser.parse_args()

def _get_log_path(mode_label: str, strategy: str) -> str:
    log_dir = "data"
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, f"{mode_label.lower()}_{strategy}.csv")

def _init_trade_id(mode_label: str, strategy: str) -> int:
    log_path = _get_log_path(mode_label, strategy)
    if os.path.exists(log_path):
        try:
            df = pd.read_csv(log_path)
            if not df.empty and "trade_id" in df.columns:
                return int(df["trade_id"].max()) + 1
        except Exception:
            pass
    return 1

def _load_state(state_file: str) -> dict:
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
    return {}

def _save_state(state_file: str, portfolio_pnl: float, current_trade: TradeRecord):
    data = {
        "portfolio_pnl": float(portfolio_pnl),
        "current_trade": current_trade.to_dict() if current_trade else None
    }
    with open(state_file, "w") as f:
        json.dump(data, f)

def _reconstruct_trade(data: dict) -> TradeRecord:
    tr = TradeRecord(
        trade_id=data["trade_id"],
        symbol=data["symbol"],
        side=data["side"],
        entry_time=datetime.strptime(data["entry_time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ist_tz),
        entry_price=data.get("entry_price", 0.0),
        size=data.get("size", 0.0),
        stop_loss_price=data.get("stop_loss_price", 0.0)
    )
    return tr

def _log_trade(trade: TradeRecord, log_path: str):
    file_exists = os.path.exists(log_path)
    trade_dict = trade.to_dict()
    headers = list(trade_dict.keys())
    
    with open(log_path, mode="a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if not file_exists:
            writer.writeheader()
        writer.writerow(trade_dict)
    
    logger.info(f"★ LOGGED {trade.side.upper()} TRADE | P&L: ${trade.pnl:,.2f} | Action saved to {log_path}")

def main():
    args = parse_args()
    is_live = config.MODE == "LIVE" and not args.dry_run
    mode_label = "LIVE" if is_live else "DEMO"
    
    # ── Auto-generate accurate Log files ────────
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now(ist_tz).strftime("%b%d_%Hh%Mm")
    log_filename = os.path.join(log_dir, f"{mode_label.lower()}_{args.strategy}_{timestamp}.log")
    
    file_handler = logging.FileHandler(log_filename)
    file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_formatter.converter = lambda *a: datetime.now(tz=ist_tz).timetuple()
    file_handler.setFormatter(file_formatter)
    logging.getLogger().addHandler(file_handler)
    
    logger.info("="*60)
    logger.info(f" STARTING BOT | Strategy: {args.strategy} | Mode: {mode_label}")
    logger.info(f" Symbol: {args.symbol} | Timeframe: {args.timeframe} | Risk: {args.risk}%")
    logger.info(f" Writing ongoing logs directly to: {log_filename}")
    logger.info("="*60)

    # ── State Initialization ──────────────────────
    state_file = f"data/trade_state_{mode_label.lower()}_{args.strategy}.json"
    state = _load_state(state_file)
    portfolio_pnl = state.get("portfolio_pnl", 0.0)
    trade_data = state.get("current_trade", None)
    
    current_trade = _reconstruct_trade(trade_data) if trade_data else None
    next_trade_id = _init_trade_id(mode_label, args.strategy)
    log_path = _get_log_path(mode_label, args.strategy)

    client = DeltaClient() if is_live else None
    fetcher = DataFetcher(client) if is_live else DataFetcher()
    
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
            api_size = 0.0
            api_entry = 0.0
            balance = getattr(config, "DEMO_INITIAL_CAPITAL", 20000.0) + portfolio_pnl
            
            if is_live:
                try:
                    balance = client.get_wallet_balance(asset="USD")
                    pos_data = client.get_position(args.symbol)
                    api_size = float(pos_data.get("size", 0))
                    api_entry = float(pos_data.get("avg_entry_price", 0))
                except Exception as e:
                    logger.error(f"Exchange Sync Error: {e}")
                    time.sleep(10)
                    continue

                # API Reconciliation (LIVE only)
                if api_size != 0 and current_trade is None:
                    # Detected manual trade or missed entry
                    side = "long" if api_size > 0 else "short"
                    size_abs = abs(api_size)
                    current_trade = TradeRecord(next_trade_id, args.symbol, side, now_ist, api_entry, size_abs, api_entry * (0.95 if side=="long" else 1.05))
                    next_trade_id += 1
                    _save_state(state_file, portfolio_pnl, current_trade)
                    logger.warning(f"Reconstructed un-tracked {side.upper()} position from API.")
                
                elif api_size == 0 and current_trade is not None:
                    # Position was closed externally (liquidated, manual close)
                    logger.warning(f"Detected orphaned local trade. Assuming external exit execution.")
                    ticker = client.get_ticker(args.symbol)
                    close_px = float(ticker.get("mark_price") or ticker.get("last_price") or ticker.get("close") or current_trade.entry_price)
                    
                    exit_fee = current_trade.size * close_px * getattr(config, "TAKER_FEE_PCT", 0.0006)
                    current_trade.close(now_ist, close_px, "manual_or_exchange", balance, fee=exit_fee)
                    
                    portfolio_pnl += current_trade.pnl
                    _log_trade(current_trade, log_path)
                    current_trade = None
                    _save_state(state_file, portfolio_pnl, current_trade)

            current_size = 0.0
            if current_trade:
                current_size = current_trade.size if current_trade.side == "long" else -current_trade.size

            pos_label = "NONE"
            if current_size > 0: pos_label = f"LONG ({current_size})"
            elif current_size < 0: pos_label = f"SHORT ({abs(current_size)})"
            
            logger.info(f"SYNC | Wallet: ${balance:,.2f} | Position: {pos_label}")

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
            
            # Temporarily silence strategy logger to prevent historical backlogging spam
            strat_logger = logging.getLogger("strategies." + args.strategy)
            strat_logger.setLevel(logging.WARNING)

            for _, row in df.reset_index().iterrows():
                candle_time_utc = row["time"]
                candle_end_utc = candle_time_utc + timedelta(seconds=candle_secs)
                
                # STRICT RULE: Only feed fully COMPLETED candles into the Strategy engine.
                # Feeding the live, incomplete candle corrupts rolling indicators and overwrites valid crossover triggers!
                if candle_end_utc <= now_utc:
                    candle = {
                        "time": row["time"], "open": float(row["open"]),
                        "high": float(row["high"]), "low": float(row["low"]),
                        "close": float(row["close"]), "volume": float(row.get("volume", 0))
                    }
                    
                    # Target only the absolute most recent completed candle to natively log its trigger if one occurs
                    if candle_end_utc + timedelta(seconds=candle_secs) > now_utc:
                        strat_logger.setLevel(logging.INFO)
                        
                    last_signal = strategy.on_candle(candle)

            # Re-enable strategy logging completely for future calls
            strat_logger.setLevel(logging.INFO)

            # Extract final active market data directly from the most recent tick
            current_price = float(df.iloc[-1]["close"])
            state_str = strategy.get_state_str() if hasattr(strategy, "get_state_str") else ""
            logger.info(f"MARKET | {args.symbol} @ ${current_price:,.2f} | Signal: {last_signal.value}{state_str}")

            # ── 4. Execute Trades ───────────────────────────
            sizer = PositionSizer(balance, args.risk / 100)
            atr = strategy.last_atr if hasattr(strategy, "last_atr") and strategy.last_atr > 0 else current_price * 0.01
            
            # Check for entry signals
            if last_signal == Signal.BUY and current_size <= 0:
                sl_price = sizer.suggested_stop_loss(current_price, "long", atr)
                size_btc = sizer.calculate_size(current_price, sl_price)
                
                if size_btc < getattr(config, "MIN_TRADE_SIZE_BTC", 0.001):
                    logger.warning(f"Position {size_btc:.6f} BTC is below minimum. Skipping.")
                elif int(size_btc * current_price) > 0:
                    size_contracts = int(size_btc * current_price)
                    logger.info(f"🚀 BUY SIGNAL DETECTED | Size: {size_contracts} contracts | SL: {sl_price:.2f}")
                    
                    if is_live:
                        client.place_order(args.symbol, "buy", size_contracts, "market_order", stop_loss=sl_price)
                    
                    # Create Entry State
                    entry_fee = size_btc * current_price * getattr(config, "TAKER_FEE_PCT", 0.0006)
                    portfolio_pnl -= entry_fee
                    
                    current_trade = TradeRecord(next_trade_id, args.symbol, "long", now_ist, current_price, size_btc, sl_price)
                    current_trade.fee = entry_fee
                    next_trade_id += 1
                    current_size = float(size_btc)
                    _save_state(state_file, portfolio_pnl, current_trade)

            elif last_signal == Signal.SELL and current_size >= 0:
                sl_price = sizer.suggested_stop_loss(current_price, "short", atr)
                size_btc = sizer.calculate_size(current_price, sl_price)
                
                if size_btc < getattr(config, "MIN_TRADE_SIZE_BTC", 0.001):
                    logger.warning(f"Position {size_btc:.6f} BTC is below minimum. Skipping.")
                elif int(size_btc * current_price) > 0:
                    size_contracts = int(size_btc * current_price)
                    logger.info(f"🚀 SELL SIGNAL DETECTED | Size: {size_contracts} contracts | SL: {sl_price:.2f}")
                    
                    if is_live:
                        client.place_order(args.symbol, "sell", size_contracts, "market_order", stop_loss=sl_price)
                    
                    entry_fee = size_btc * current_price * getattr(config, "TAKER_FEE_PCT", 0.0006)
                    portfolio_pnl -= entry_fee
                    
                    current_trade = TradeRecord(next_trade_id, args.symbol, "short", now_ist, current_price, size_btc, sl_price)
                    current_trade.fee = entry_fee
                    next_trade_id += 1
                    current_size = -float(size_btc)
                    _save_state(state_file, portfolio_pnl, current_trade)

            # ── 5. Heartbeat & Wait for Next Candle ─────────────────────
            seconds_into_candle = now_ist.minute % int(args.timeframe.replace("m", "")) * 60 + now_ist.second
            wait_time = max(candle_secs - seconds_into_candle + 2, 10) # +2s for buffer
            next_run_ts = time.time() + wait_time
            
            logger.info(f"WAIT | Next candle check at {(now_ist + timedelta(seconds=wait_time)).strftime('%H:%M:%S')} IST...")
            
            if current_size != 0:
                target_p = strategy.last_upper if current_size > 0 else strategy.last_lower
                logger.info(f"💓 HEARTBEAT | Starting monitor (Target Ratchet/End: ${target_p:,.2f})")

            tick_count = 0
            # Heartbeat Loop for Trailing Stop Check
            while time.time() < next_run_ts - 2: 
                if current_size == 0:
                    time.sleep(10)
                    continue
                
                time.sleep(3)
                tick_count += 1
                
                try:
                    # Fetching ticker handles DEMO mode gracefully as long as API isn't blocked. 
                    # For total API bypass in Demo Mode, we could use binance websocket, but Delta API public ticker is limitless enough.
                    ticker = fetcher.client.get_ticker(args.symbol) if is_live else DeltaClient().get_ticker(args.symbol)
                    lp = float(ticker.get("mark_price") or ticker.get("last_price") or ticker.get("close") or 0)
                    if lp == 0: continue
                    
                    # ── Trailing SL Ratchet Check ──────────────────────
                    if hasattr(strategy, "get_trailing_sl") and current_trade:
                        new_sl = strategy.get_trailing_sl(current_trade.side, current_trade.stop_loss_price, lp, strategy.last_atr)
                        if new_sl != current_trade.stop_loss_price:
                            logger.info(f"  [TRAIL] SL Ratchet: ${current_trade.stop_loss_price:,.2f} -> ${new_sl:,.2f}")
                            current_trade.stop_loss_price = new_sl
                            _save_state(state_file, portfolio_pnl, current_trade)
                            
                    if tick_count % 5 == 0:
                        logger.info(f"  [TICK] ${lp:,.2f} | Active SL: ${current_trade.stop_loss_price:,.2f}")
                    
                    # ── Evaluate SL Exit Trigger ───────────────────────
                    exit_triggered = False
                    if current_size > 0 and lp <= current_trade.stop_loss_price:
                        exit_triggered = True
                    elif current_size < 0 and lp >= current_trade.stop_loss_price:
                        exit_triggered = True
                    
                    if exit_triggered:
                        logger.info(f"🎯 STOP LOSS HIT: ${lp:,.2f}")
                        if is_live:
                            exit_side = "sell" if current_size > 0 else "buy"
                            client.place_order(args.symbol, exit_side, abs(current_size), "market_order")
                        
                        # Conclude Trade and log strictly formatted journal entry
                        exit_fee = current_trade.size * lp * getattr(config, "TAKER_FEE_PCT", 0.0006)
                        current_trade.close(datetime.now(ist_tz), lp, "stop_loss", balance, fee=exit_fee)
                        portfolio_pnl += current_trade.pnl
                        _log_trade(current_trade, log_path)
                        
                        current_size = 0 
                        current_trade = None
                        _save_state(state_file, portfolio_pnl, current_trade)
                        break 
                        
                except Exception as e:
                    logger.warning(f"Heartbeat monitor error: {e}")
                    time.sleep(5)
            
            final_wait = max(next_run_ts - time.time(), 0)
            if final_wait > 0:
                time.sleep(final_wait)

    except KeyboardInterrupt:
        logger.info("\nBot stopped manually. Safe trading!")

if __name__ == "__main__":
    main()
