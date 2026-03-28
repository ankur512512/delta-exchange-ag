"""
dashboard/app.py — Streamlit web dashboard for Delta Exchange backtesting and Live Monitoring.

Run with:
    streamlit run dashboard/app.py
"""
import sys
import os
import importlib
from datetime import datetime, timedelta

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import config
from core.data_fetcher import DataFetcher, RESOLUTION_SECONDS
from core.backtest_engine import BacktestEngine
from reports.metrics import compute_metrics
from core.delta_client import DeltaClient

# ─────────────────────────────────────────────
#  Page config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Delta Antigravity — Trading Hub",
    page_icon="🤖",
    layout="wide",
)

# ─────────────────────────────────────────────
#  Helper functions
# ─────────────────────────────────────────────

def _discover_strategies() -> list:
    strategies_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "strategies")
    options = []
    if os.path.exists(strategies_dir):
        for fname in os.listdir(strategies_dir):
            if fname.endswith(".py") and fname not in ("__init__.py", "base_strategy.py"):
                options.append(fname.replace(".py", ""))
    return options or ["bollinger_bands"]

def _load_strategy(name: str, **kwargs):
    module = importlib.import_module(f"strategies.{name}")
    class_name = "".join(part.title() for part in name.split("_")) + "Strategy"
    cls = getattr(module, class_name)
    return cls(**kwargs)

# ─────────────────────────────────────────────
#  Sidebar (Shared)
# ─────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.shields.io/badge/Delta-Antigravity-00d4aa?style=for-the-badge", use_container_width=True)
    st.caption(f"**Current Mode:** `{config.MODE}`")
    
    if config.MODE == "LIVE":
        st.warning("⚠️ PROD MODE ACTIVE. Trading is REAL.")
    else:
        st.info("🧪 BACKTEST MODE. Trading is simulated.")

# ─────────────────────────────────────────────
#  Main Tabs
# ─────────────────────────────────────────────
tab1, tab2 = st.tabs(["📊 Backtest Engine", "📡 Live Monitor"])

with tab1:
    st.header("Strategy Backtester")
    
    # Inner sidebar controls (nested under tab logic)
    with st.expander("⚙️ Backtest Settings", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            symbol = st.selectbox("Symbol", ["BTCUSD", "ETHUSD"], index=0)
            timeframe = st.selectbox("Timeframe", list(RESOLUTION_SECONDS.keys()), index=2) # 5m
        with c2:
            d_start = datetime.strptime(config.BACKTEST_START, "%Y-%m-%d")
            d_end   = datetime.strptime(config.BACKTEST_END, "%Y-%m-%d")
            start_date = st.date_input("Start Date", value=d_start)
            end_date = st.date_input("End Date", value=d_end)
        with c3:
            initial_capital = st.number_input("Initial Capital (USD)", value=10_000.0)
            max_risk_pct = st.slider("Max Risk (%)", 0.1, 2.0, 0.3) / 100
            trailing_stop_enabled = st.checkbox("Enable Trailing Stop Loss", value=True)
            config.TRAILING_STOP_ENABLED = trailing_stop_enabled

    strategy_options = _discover_strategies()
    strategy_name = st.selectbox("Select Strategy", strategy_options)
    
    run_button = st.button("▶ Run Backtest", type="primary")

    if run_button:
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        with st.spinner("Fetching data and simulating..."):
            fetcher = DataFetcher()
            df = fetcher.fetch(symbol, timeframe, start_str, end_str)
            
            strategy = _load_strategy(strategy_name)
            engine = BacktestEngine(strategy, initial_capital, max_risk_pct)
            result = engine.run(df, symbol, timeframe, start_str, end_str)
            
            metrics = compute_metrics(result.trade_log.closed_trades, result.equity_curve, result.initial_capital, timeframe)

        # Dashboard layout
        st.success(f"Simulation Complete: {len(result.trade_log.closed_trades)} trades simulated.")
        
        # Performance Summary Cards
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Total Return", f"{metrics['total_return_pct']}%")
        k2.metric("Total P&L", f"${metrics['total_pnl']:,.2f}")
        k3.metric("Win Rate", f"{metrics['win_rate_pct']}%")
        k4.metric("Sharpe Ratio", str(metrics['sharpe_ratio']))
        k5.metric("Max Drawdown", f"{metrics['max_drawdown_pct']}%")
        
        # Performance Details Table
        st.markdown("### 📈 Performance Summary")
        m1, m2, m3, m4 = st.columns(4)
        
        with m1:
            st.markdown("**Overview**")
            st.caption(f"Total Trades: {metrics['total_trades']}")
            st.caption(f"Winning Trades: {metrics['winning_trades']}")
            st.caption(f"Losing Trades: {metrics['losing_trades']}")
            st.caption(f"Profit Factor: {metrics['profit_factor']}")
        
        with m2:
            st.markdown("**P&L Details**")
            st.caption(f"Initial Capital: ${metrics['initial_capital']:,.2f}")
            st.caption(f"Final Capital: ${metrics['final_capital']:,.2f}")
            st.caption(f"Annualized Return: {metrics['annualised_return_pct']}%")
        
        with m3:
            st.markdown("**Per-Trade Stats**")
            st.caption(f"Avg Trade P&L: ${metrics['avg_trade_pnl']:,.2f}")
            st.caption(f"Avg Winner: ${metrics['avg_winner']:,.2f}")
            st.caption(f"Avg Loser: ${metrics['avg_loser']:,.2f}")
            st.caption(f"Avg Holding: {metrics['avg_holding_hours']}h")
            
        with m4:
            st.markdown("**Risk Analysis**")
            st.caption(f"Max DD (USD): ${metrics['max_drawdown_usd']:,.2f}")
            st.caption(f"Max DD Duration: {metrics['max_drawdown_duration_candles']} candles")
            st.caption(f"Max Win Streak: {metrics['max_consecutive_wins']}")
            st.caption(f"Max Loss Streak: {metrics['max_consecutive_losses']}")
        
        # Charts
        st.plotly_chart(go.Figure(data=[go.Scatter(x=result.equity_curve.index, y=result.equity_curve.values, line=dict(color="#00d4aa"))]).update_layout(title="Equity Curve", template="plotly_dark"), use_container_width=True)
        
        with st.expander("📖 View Equity History Table"):
            st.dataframe(result.equity_curve.rename("Wallet Balance"), use_container_width=True)
        
        # Trade Log
        st.markdown("### Detailed Trade Log")
        st.dataframe(result.trade_log.to_dataframe(), use_container_width=True, hide_index=True)


with tab2:
    st.header("Live Trading Monitor")
    
    # ── 1. Account Status ───────────────────────────
    st.markdown("### 🏦 Multi-Account Status")
    client = DeltaClient()
    
    if config.API_KEY and config.API_SECRET:
        try:
            balance = client.get_wallet_balance(asset="USD")
            pos = client.get_position(config.SYMBOL)
            
            c1, c2 = st.columns(2)
            c1.metric("Available Balance", f"${balance:,.2f}")
            
            if pos:
                size = float(pos.get("size", 0))
                entry = float(pos.get("avg_entry_price", 0))
                pnl = float(pos.get("unrealized_pnl", 0))
                c2.metric("Open Position", f"{size} contracts", delta=f"${pnl:,.2f} U-PnL")
                st.info(f"Entry Price: ${entry:,.2f}")
            else:
                c2.metric("Open Position", "NONE")
        except Exception as e:
            st.error(f"Could not fetch account data: {e}")
    else:
        st.warning("⚠️ API keys not configured in `.env`. Showing simulated view.")

    # ── 2. Local Live Trade Log ─────────────────────
    st.markdown("### 📜 Recent Bot Actions")
    st.caption("These are logged by `run_live.py` into `data/live_trades.csv`.")
    
    log_path = "data/live_trades.csv"
    if os.path.exists(log_path):
        try:
            live_df = pd.read_csv(log_path)
            st.dataframe(live_df.sort_values("timestamp", ascending=False), use_container_width=True, hide_index=True)
            
            # Simple Chart of Live Actions
            if len(live_df) > 0:
                fig = go.Figure(data=[go.Scatter(x=pd.to_datetime(live_df["timestamp"]), y=live_df["price"], mode="markers+lines", marker=dict(color=live_df["side"].apply(lambda s: "#00d4aa" if s == "BUY" else "#ff4d6d")))])
                fig.update_layout(title="Live Entries/Exits", template="plotly_dark", height=300)
                st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.error(f"Error reading live trades: {e}")
    else:
        st.info("No live trade history found. Start the bot with `python run_live.py` to see data here.")

    st.markdown("---")
    if st.button("🔄 Refresh Data"):
        st.rerun()
