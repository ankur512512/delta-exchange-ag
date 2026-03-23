# Delta Antigravity — Pro Trading Bot

Delta Antigravity is a robust, event-driven algorithmic trading system designed for **Delta Exchange India**. It features a "Falling Knife Protection" strategy, modular architecture for backtesting, and a real-time monitoring dashboard.

---

## 🚀 Key Features

*   **Live Trading Engine (`run_live.py`)**: Executes real-time trades on Delta Exchange India using HMAC-signed REST API calls. 
*   **Backtest Suite (`run_backtest.py`)**: Simulate strategies on years of historical OHLCV data fetched directly from Delta's history servers.
*   **Dynamic Position Sizing**: Automatically calculates trade size based on a fixed-risk percentage (e.g., risk 0.3% of portfolio per trade) using ATR-based stop losses.
*   **Streamlit Dashboard**: A beautiful, dark-mode web interface to visualize backtest results, equity curves, and monitor live account status.
*   **Smart Signal Confirmation**: Strategy waits for an RSI "cross-back" (rebound) before entering during high volatility.

---

## 📁 Project Structure

```text
.
├── config.py           # Central configuration (BASE_URL, Risk, Timeframes)
├── run_backtest.py     # CLI for historical simulations
├── run_live.py         # CLI for real-money trading (BE CAREFUL!)
├── core/               # Core Engine
│   ├── delta_client.py # V2 API Client (Fixed for India subdomain & HMAC)
│   ├── position_sizer.py # Risk-to-Size calculation logic
│   ├── backtest_engine.py # Event-loop for simulations
│   └── data_fetcher.py # Paginated historical data downloader
├── strategies/         # Strategy implementations
│   └── bollinger_bands.py # Primary mean-reversion strategy
├── dashboard/          # Streamlit UI
│   └── app.py          # Dashboard entry point
├── data/               # Local OHLCV cache and trade logs
└── reports/            # Generated HTML backtest reports
```

---

## 🛠️ Setup Instructions

### 1. Prerequisites
*   Python 3.8+
*   Delta Exchange India API Key & Secret

### 2. Manual Installation (Virtual Environment)
It is highly recommended to use a virtual environment to manage dependencies.

```bash
# Clone the repository (if applicable)
# git clone <repo-url>
# cd delta-antigravity

# Create a virtual environment
python3 -m venv venv

# Activate the environment
# On Linux/macOS:
source venv/bin/activate
# On Windows:
# .\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration
Create a `.env` file in the root directory and add your API credentials:

```ini
DELTA_API_KEY="your_api_key_here"
DELTA_API_SECRET="your_api_secret_here"
MODE="LIVE"  # Change to "BACKTEST" to disable real orders via config
```

---

## 📈 How to Run

### Run a Backtest
Simulate the Bollinger Bands strategy on BTCUSD for the last 30 days:
```bash
python run_backtest.py --strategy bollinger_bands --symbol BTCUSD --timeframe 5m
```
*Results will save an HTML report in `reports/output/`.*

### Start Live Trading
Before running real money, verify your settings with `--dry-run`:
```bash
python run_live.py --strategy bollinger_bands --dry-run
```
When ready for real execution:
```bash
python run_live.py --strategy bollinger_bands
```

### Launch the Dashboard
Visualize your trading hub and run backtests through a web interface:
```bash
streamlit run dashboard/app.py
```

---

## 🖥️ Streamlit Dashboard Features

The project includes a powerful web dashboard for both research and monitoring:

### 1. 📊 Backtest Engine Tab
*   **Interactive Parameters**: Configure Symbol, Timeframe, Date Range, and Risk directly from the UI.
*   **One-Click Simulation**: Execute backtests without touching the command line.
*   **Performance Metrics**: View Total Return, Win Rate, P&L, and Sharpe Ratio instantly.
*   **Visual Equity Curve**: Interactive Plotly charts to visualize drawdown and growth.
*   **Detailed Trade Log**: Expandable table of every entry, exit, and P&L result.

### 2. 📡 Live Monitor Tab
*   **Real-Time Account Status**: View your available USD balance and open position details (contracts, entry price, unrealized P&L).
*   **Bot Activity Tracking**: Monitor the latest actions taken by `run_live.py` via the local `live_trades.csv` log.
*   **Live Charts**: Scatter plots of recent entries and exits on a price timeline.
*   **Quick Refresh**: Sync with the Delta Exchange API at any time to get the latest portfolio status.

---

## 🛡️ Strategy: Aggressive Bollinger Bands Mean Reversion

The `bollinger_bands` strategy is now configured for high-frequency mean reversion.

1.  **Entry**: Signals a **BUY** as soon as a candle closes below the **Lower Band** and a **SELL** as soon as it closes above the **Upper Band**.
2.  **Exit (Band-to-Band)**: Long positions are automatically closed (and potentially flipped) when the price touches the **Upper Band**. Similarly for short positions at the **Lower Band**.
3.  **Risk**: Uses a dynamic **ATR-based Stop Loss** to protect against runaway trends.

---

## ⚠️ Important Notes (For Live Trading)

*   **Minimum Order Size**: Delta Exchange India enforces a minimum trade size of **0.001 BTC** for many pairs. The bot includes a safety check in `run_live.py` to skip signals smaller than this.
*   **Contract Conversion**: For `BTCUSD` Inverse Perpetuals, 1 contract = $1. The bot automatically converts your BTC-denominated risk into the correct number of integer contracts.
*   **Timezone**: All logs are localized to **Asia/Kolkata (IST)** for easier monitoring in India.

---
*Disclaimer: Trading cryptocurrencies involves significant risk. This bot is provided for educational/tooling purposes. Use at your own risk.*
