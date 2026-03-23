"""
config.py — Central configuration for the Delta Exchange trading system.

Edit values here, or override per-run using CLI arguments in run_backtest.py / run_live.py.
To switch to live trading: set MODE=LIVE in your .env file (or pass --mode live on CLI).
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
#  API
# ─────────────────────────────────────────────
BASE_URL = "https://api.india.delta.exchange"
API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")

# ─────────────────────────────────────────────
#  Trading Mode
#  "BACKTEST" → simulate on historical data (safe)
#  "LIVE"     → place real orders via API (real money!)
# ─────────────────────────────────────────────
MODE = os.getenv("MODE", "BACKTEST").upper()
VALID_MODES = {"BACKTEST", "LIVE"}
if MODE not in VALID_MODES:
    raise ValueError(f"Invalid MODE '{MODE}'. Must be one of: {VALID_MODES}")

# ─────────────────────────────────────────────
#  Default Instrument
# ─────────────────────────────────────────────
SYMBOL = "BTCUSD"

# Supported timeframes (Delta Exchange resolution codes)
# 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 1d, 1w
TIMEFRAME = "5m"

# ─────────────────────────────────────────────
#  Backtest Date Range  (YYYY-MM-DD strings)
# ─────────────────────────────────────────────
from datetime import datetime, timedelta
BACKTEST_END   = datetime.now().strftime("%Y-%m-%d")
BACKTEST_START = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

# ─────────────────────────────────────────────
#  Risk Management
# ─────────────────────────────────────────────
# Maximum portfolio risk per trade (0.3% = 0.003)
MAX_RISK_PER_TRADE = 0.003

# Initial simulated portfolio value (USD) for backtesting
INITIAL_CAPITAL = 10_000.0

# Minimum trade size in BTC (Delta India minimum for some pairs)
MIN_TRADE_SIZE_BTC = 0.001

# ─────────────────────────────────────────────
#  Data Cache
# ─────────────────────────────────────────────
# Set to True to cache OHLCV data locally as CSV (recommended)
USE_CACHE = True
CACHE_DIR = "data/cache"

# ─────────────────────────────────────────────
#  Reports
# ─────────────────────────────────────────────
REPORTS_DIR = "reports/output"

# ─────────────────────────────────────────────
#  API Constraints
# ─────────────────────────────────────────────
MAX_CANDLES_PER_REQUEST = 2000   # Delta Exchange hard limit
API_REQUEST_DELAY_SECS  = 0.2   # polite delay between paginated requests
