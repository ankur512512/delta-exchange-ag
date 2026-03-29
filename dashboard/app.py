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
from core.trade_log import TradeRecord

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
    st.image("https://img.shields.io/badge/Delta-Antigravity-00d4aa?style=for-the-badge", width='stretch')
    st.caption(f"**Current Mode:** `{config.MODE}`")
    
    if config.MODE == "LIVE":
        st.warning("⚠️ PROD MODE ACTIVE. Trading is REAL.")
    elif config.MODE == "DEMO":
        st.info("🧪 DEMO MODE. Trades hit live market data, but not Delta.")
    else:
        st.info("📊 BACKTEST MODE. Trading is simulated.")

# ─────────────────────────────────────────────
#  Main Tabs
# ─────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📊 Backtester", "📡 Live Monitor", "📔 Trade Journals"])

with tab1:
    st.header("Strategy Backtester")
    
    with st.expander("⚙️ Backtest Settings", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            sym_options = ["BTCUSD", "ETHUSD"]
            sym_index = sym_options.index(config.SYMBOL) if config.SYMBOL in sym_options else 0
            symbol = st.selectbox("Symbol", sym_options, index=sym_index)
            
            tf_options = list(RESOLUTION_SECONDS.keys())
            tf_index = tf_options.index(config.TIMEFRAME) if config.TIMEFRAME in tf_options else 2
            timeframe = st.selectbox("Timeframe", tf_options, index=tf_index)
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

        st.success(f"Simulation Complete: {len(result.trade_log.closed_trades)} trades simulated.")
        
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Total Return", f"{metrics['total_return_pct']}%")
        k2.metric("Net P&L", f"${metrics['total_pnl']:,.2f}")
        k3.metric("Win Rate", f"{metrics['win_rate_pct']}%")
        k4.metric("Sharpe Ratio", str(metrics['sharpe_ratio']))
        k5.metric("Max Drawdown", f"{metrics['max_drawdown_pct']}%")
        k6.metric("Execution Fees", f"${metrics['total_fees_paid']:,.2f}")
        
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
        
        fig = go.Figure(data=[go.Scatter(x=result.equity_curve.index, y=result.equity_curve.values, line=dict(color="#00d4aa"))])
        fig.update_layout(title="Equity Curve", template="plotly_dark")
        st.plotly_chart(fig, width='stretch')
        
        with st.expander("📖 View Equity History Table"):
            st.dataframe(result.equity_curve.rename("Wallet Balance"), width='stretch')
        
        st.markdown("### Detailed Trade Log")
        st.dataframe(result.trade_log.to_dataframe(), width='stretch', hide_index=True)


with tab2:
    st.header("Live Trading Monitor")
    
    st.markdown("### 🏦 Multi-Account Status")
    client = DeltaClient()
    
    if config.MODE in ["LIVE", "DEMO"]:
        try:
            if config.MODE == "LIVE":
                balance = client.get_wallet_balance(asset="USD")
                pos_data = client.get_position(config.SYMBOL)
            else:
                balance = getattr(config, "DEMO_INITIAL_CAPITAL", 20000.0)
                pos_data = {}
            
            c1, c2 = st.columns(2)
            c1.metric("Available Balance", f"${balance:,.2f}")
            
            if pos_data:
                size = float(pos_data.get("size", 0))
                entry = float(pos_data.get("avg_entry_price", 0))
                pnl = float(pos_data.get("unrealized_pnl", 0))
                c2.metric("Open Position", f"{size} contracts", delta=f"${pnl:,.2f} U-PnL")
                st.info(f"Entry Price: ${entry:,.2f}")
            else:
                c2.metric("Open Position", "NONE / CACHED")
        except Exception as e:
            st.error(f"Could not fetch account data: {e}")
    else:
        st.warning("⚠️ Switch to LIVE or DEMO mode to view active accounts.")
        
    st.markdown("---")
    if st.button("🔄 Refresh API Data"):
        st.rerun()

with tab3:
    st.header("Journal Analytics")
    st.markdown("Analyze your real or demo market journals against identical backtest parameters.")
    
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    journal_files = []
    if os.path.exists(log_dir):
        journal_files = [f for f in os.listdir(log_dir) if (f.startswith("live_") or f.startswith("demo_")) and f != "live_trades.csv"]
    
    if not journal_files:
        st.info("No recorded Live or Demo trades found yet.")
    else:
        selected_file = st.selectbox("Select Trading Journal", sorted(journal_files))
        
        if selected_file:
            st.markdown(f"#### Processing `{selected_file}`")
            df = pd.read_csv(os.path.join(log_dir, selected_file))
            
            if df.empty:
                st.warning("Journal is completely empty (no trades closed yet).")
            else:
                with st.spinner("Processing Trade Log..."):
                    trades = []
                    initial_cap = getattr(config, "DEMO_INITIAL_CAPITAL", 20000.0) if "demo" in selected_file else config.INITIAL_CAPITAL
                    
                    for _, row in df.iterrows():
                        tr = TradeRecord(
                            trade_id=row['trade_id'],
                            symbol=row['symbol'],
                            side=row['side'],
                            entry_time=pd.to_datetime(row['entry_time']),
                            entry_price=float(row['entry_price']),
                            size=float(row['size']),
                            stop_loss_price=float(row['stop_loss_price']),
                            exit_time=pd.to_datetime(row['exit_time']) if pd.notnull(row['exit_time']) else None,
                            exit_price=float(row['exit_price']) if pd.notnull(row['exit_price']) else None,
                            exit_reason=str(row.get('exit_reason')),
                            pnl=float(row.get('pnl', 0.0)),
                            pnl_pct=float(row.get('pnl_pct', 0.0)),
                            portfolio_value=float(row.get('portfolio_value', initial_cap)),
                        )
                        tr.fee = float(row.get('fee', 0.0))
                        trades.append(tr)
                        
                    # Reconstruct Equity Curve using exit times 
                    # Note: Assumes chronological order of trade completion
                    eq_dict = {trades[0].entry_time: initial_cap} # Initial anchor
                    for t in trades:
                        if t.exit_time:
                            eq_dict[t.exit_time] = t.portfolio_value
                            
                    equity_curve = pd.Series(eq_dict).sort_index()

                    metrics = compute_metrics(trades, equity_curve, initial_cap, config.TIMEFRAME)

                # Rendering Analytics
                k1, k2, k3, k4, k5, k6 = st.columns(6)
                k1.metric("Total Return", f"{metrics['total_return_pct']}%")
                k2.metric("Net P&L", f"${metrics['total_pnl']:,.2f}")
                k3.metric("Win Rate", f"{metrics['win_rate_pct']}%")
                k4.metric("Sharpe Ratio", str(metrics['sharpe_ratio']))
                k5.metric("Max Drawdown", f"{metrics['max_drawdown_pct']}%")
                k6.metric("Execution Fees", f"${metrics['total_fees_paid']:,.2f}")
                
                # Equity Curve
                fig = go.Figure(data=[go.Scatter(x=equity_curve.index, y=equity_curve.values, mode='lines', line=dict(color="#00d4aa"))])
                fig.update_layout(title="Live Equity Curve vs Time", template="plotly_dark")
                st.plotly_chart(fig, width='stretch')
                
                # Trade Table
                st.markdown("### Completed Trade Leger")
                st.dataframe(df, width='stretch', hide_index=True)
