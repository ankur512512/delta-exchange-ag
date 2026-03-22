"""
dashboard/app.py — Streamlit web dashboard for Delta Exchange backtesting.

Run with:
    streamlit run dashboard/app.py

Features:
- Sidebar: select symbol, timeframe, strategy, date range, initial capital
- Main view: equity curve, KPI metrics cards, drawdown chart, trade log table
- Compare multiple backtest runs
"""
import sys
import os
import importlib
from datetime import datetime, timedelta

# Ensure project root is in path (when running from dashboard/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import config
from core.data_fetcher import DataFetcher, RESOLUTION_SECONDS
from core.backtest_engine import BacktestEngine
from reports.metrics import compute_metrics

# ─────────────────────────────────────────────
#  Page config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Delta Antigravity — Backtester",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
#  Custom CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
  .main { background-color: #0f1117; }
  .kpi-row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
  .kpi-card { background: #1a1d2e; border: 1px solid #2d2f3e; border-radius: 10px;
              padding: 16px 20px; flex: 1; min-width: 140px; }
  .kpi-card .label { font-size: 11px; color: #888; text-transform: uppercase;
                      letter-spacing: 0.08em; margin-bottom: 4px; }
  .kpi-card .val { font-size: 22px; font-weight: 700; color: #fff; }
  .kpi-card .pos { color: #00d4aa; }
  .kpi-card .neg { color: #ff4d6d; }
  div[data-testid="metric-container"] { background: #1a1d2e; border: 1px solid #2d2f3e;
    border-radius: 10px; padding: 12px; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  Helper functions (must be defined before sidebar)
# ─────────────────────────────────────────────

def _discover_strategies() -> list:
    """Scan strategies/ folder and return available strategy names."""
    strategies_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "strategies")
    options = []
    for fname in os.listdir(strategies_dir):
        if fname.endswith(".py") and fname not in ("__init__.py", "base_strategy.py"):
            options.append(fname.replace(".py", ""))
    return options or ["bollinger_bands"]


def _load_strategy(name: str, **kwargs):
    """Dynamically import and instantiate a strategy class."""
    module = importlib.import_module(f"strategies.{name}")
    class_name = "".join(part.title() for part in name.split("_")) + "Strategy"
    cls = getattr(module, class_name)
    return cls(**kwargs)


# ─────────────────────────────────────────────
#  Sidebar controls
# ─────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.shields.io/badge/Delta-Antigravity-00d4aa?style=for-the-badge", use_container_width=True)
    st.title("⚙️ Backtest Settings")

    symbol = st.selectbox("Symbol", ["BTCUSD", "ETHUSD"], index=0)

    timeframe = st.selectbox(
        "Timeframe",
        list(RESOLUTION_SECONDS.keys()),
        index=list(RESOLUTION_SECONDS.keys()).index("5m"),
    )

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", value=datetime.now() - timedelta(days=365))
    with col2:
        end_date = st.date_input("End Date", value=datetime.now())

    # Strategy picker — auto-discover strategy files
    strategy_options = _discover_strategies()
    strategy_name = st.selectbox("Strategy", strategy_options)

    st.markdown("---")
    st.subheader("Risk Settings")
    initial_capital = st.number_input("Initial Capital (USD)", value=10_000.0, step=1_000.0, min_value=100.0)
    max_risk_pct    = st.slider("Max Risk Per Trade (%)", 0.1, 2.0, 0.3, 0.05) / 100

    st.markdown("---")
    st.subheader("Bollinger Bands Params")
    bb_period      = st.slider("BB Period", 5, 50, 20)
    bb_std         = st.slider("BB Std Dev", 1.0, 3.5, 2.0, 0.1)
    rsi_period     = st.slider("RSI Period", 5, 30, 14)
    rsi_oversold   = st.slider("RSI Oversold", 20, 45, 35)
    rsi_overbought = st.slider("RSI Overbought", 55, 80, 65)

    run_button = st.button("▶ Run Backtest", type="primary", use_container_width=True)

    st.markdown("---")
    st.caption(f"**Mode:** `{config.MODE}`")
    if config.MODE == "LIVE":
        st.warning("⚠️ LIVE mode is active. Set MODE=BACKTEST in .env for simulation.")


def _discover_strategies() -> list:
    """Scan strategies/ folder and return available strategy names."""
    strategies_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "strategies")
    options = []
    for fname in os.listdir(strategies_dir):
        if fname.endswith(".py") and fname not in ("__init__.py", "base_strategy.py"):
            options.append(fname.replace(".py", ""))
    return options or ["bollinger_bands"]


def _load_strategy(name: str, **kwargs):
    """Dynamically import and instantiate a strategy class."""
    module = importlib.import_module(f"strategies.{name}")
    # Convention: class name is CamelCase version of module name
    class_name = "".join(part.title() for part in name.split("_")) + "Strategy"
    cls = getattr(module, class_name)
    return cls(**kwargs)


# ─────────────────────────────────────────────
#  Main content
# ─────────────────────────────────────────────
st.title("📈 Delta Antigravity — Backtester")
st.caption("Backtest crypto trading strategies on Delta Exchange India. All timestamps are in **IST (UTC+5:30)**.")

if run_button:
    start_str = start_date.strftime("%Y-%m-%d")
    end_str   = end_date.strftime("%Y-%m-%d")

    with st.spinner(f"Fetching {symbol} {timeframe} data ({start_str} → {end_str})…"):
        fetcher = DataFetcher()
        try:
            df = fetcher.fetch(symbol, timeframe, start_str, end_str)
        except Exception as e:
            st.error(f"Data fetch failed: {e}")
            st.stop()

    st.success(f"✅ Loaded **{len(df):,}** candles", icon="📊")

    with st.spinner("Running backtest…"):
        strategy_kwargs = {}
        if strategy_name == "bollinger_bands":
            strategy_kwargs = dict(
                bb_period=bb_period, bb_std_dev=bb_std,
                rsi_period=rsi_period, rsi_oversold=rsi_oversold,
                rsi_overbought=rsi_overbought,
            )
        strategy = _load_strategy(strategy_name, **strategy_kwargs)
        engine   = BacktestEngine(strategy, initial_capital, max_risk_pct)
        result   = engine.run(df, symbol, timeframe, start_str, end_str)

    metrics = compute_metrics(
        result.trade_log.closed_trades,
        result.equity_curve,
        result.initial_capital,
        timeframe,
    )

    # ── KPI Metrics ──────────────────────────────
    st.markdown("### Performance Summary")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    ret_color   = "normal" if metrics["total_return_pct"] >= 0 else "inverse"
    pnl_color   = "normal" if metrics["total_pnl"] >= 0 else "inverse"
    c1.metric("Total Return", f"{metrics['total_return_pct']}%")
    c2.metric("Total P&L",    f"${metrics['total_pnl']:,.2f}")
    c3.metric("Win Rate",     f"{metrics['win_rate_pct']}%")
    c4.metric("Sharpe",       str(metrics["sharpe_ratio"]))
    c5.metric("Max Drawdown", f"{metrics['max_drawdown_pct']}%")
    c6.metric("Trades",       str(metrics["total_trades"]))

    st.divider()

    # ── Equity Curve ──────────────────────────────
    st.markdown("### Equity Curve")
    equity = result.equity_curve
    if not equity.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=equity.index, y=equity.values, mode="lines",
            name="Portfolio", line=dict(color="#00d4aa", width=2),
            fill="tozeroy", fillcolor="rgba(0,212,170,0.07)",
        ))
        fig.add_hline(y=initial_capital, line_dash="dash",
                      line_color="rgba(255,255,255,0.25)")
        fig.update_layout(
            template="plotly_dark", paper_bgcolor="#0f1117",
            plot_bgcolor="#0f1117", height=380,
            xaxis_title="Date", yaxis_title="USD",
            margin=dict(l=40, r=20, t=20, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Drawdown ──────────────────────────────────
    st.markdown("### Drawdown")
    if not equity.empty:
        rolling_max = equity.cummax()
        drawdown    = (equity - rolling_max) / rolling_max * 100
        dd_fig = go.Figure()
        dd_fig.add_trace(go.Scatter(
            x=drawdown.index, y=drawdown.values, mode="lines",
            name="Drawdown %", line=dict(color="#ff4d6d", width=1.5),
            fill="tozeroy", fillcolor="rgba(255,77,109,0.1)",
        ))
        dd_fig.update_layout(
            template="plotly_dark", paper_bgcolor="#0f1117",
            plot_bgcolor="#0f1117", height=280,
            xaxis_title="Date", yaxis_title="Drawdown (%)",
            margin=dict(l=40, r=20, t=20, b=40),
        )
        st.plotly_chart(dd_fig, use_container_width=True)

    st.divider()

    # ── Detailed Metrics Table ────────────────────
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("### P&L Breakdown")
        st.dataframe(pd.DataFrame({
            "Metric": ["Initial Capital", "Final Capital", "Total P&L",
                       "Total Return", "Annualised Return",
                       "Avg Trade P&L", "Avg Winner", "Avg Loser"],
            "Value": [
                f"${metrics['initial_capital']:,.2f}",
                f"${metrics['final_capital']:,.2f}",
                f"${metrics['total_pnl']:,.2f}",
                f"{metrics['total_return_pct']}%",
                f"{metrics['annualised_return_pct']}%",
                f"${metrics['avg_trade_pnl']:,.2f}",
                f"${metrics['avg_winner']:,.2f}",
                f"${metrics['avg_loser']:,.2f}",
            ],
        }), use_container_width=True, hide_index=True)

    with col_b:
        st.markdown("### Risk Metrics")
        st.dataframe(pd.DataFrame({
            "Metric": ["Win Rate", "Profit Factor", "Sharpe Ratio",
                       "Max Drawdown (USD)", "Max Drawdown (%)",
                       "Max Consec. Wins", "Max Consec. Losses",
                       "Avg Holding (hours)"],
            "Value": [
                f"{metrics['win_rate_pct']}%",
                str(metrics["profit_factor"]),
                str(metrics["sharpe_ratio"]),
                f"${metrics['max_drawdown_usd']:,.2f}",
                f"{metrics['max_drawdown_pct']}%",
                str(metrics["max_consecutive_wins"]),
                str(metrics["max_consecutive_losses"]),
                f"{metrics['avg_holding_hours']}h",
            ],
        }), use_container_width=True, hide_index=True)

    st.divider()

    # ── Trade Log ─────────────────────────────────
    st.markdown("### Trade Log")
    trades_df = result.trade_log.to_dataframe()
    if not trades_df.empty:
        st.dataframe(trades_df, use_container_width=True, hide_index=True)
    else:
        st.info("No trades executed in this backtest run.")

    # ── HTML Report Download ──────────────────────
    st.divider()
    from reports.html_reporter import generate_report
    report_path = generate_report(result)
    with open(report_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    st.download_button(
        label="⬇️ Download HTML Report",
        data=html_content,
        file_name=os.path.basename(report_path),
        mime="text/html",
        use_container_width=True,
    )

else:
    # Landing screen
    st.info("👈 Configure your backtest parameters in the sidebar and click **▶ Run Backtest** to start.", icon="ℹ️")
    st.markdown("""
    ### Getting Started
    1. **Set your `.env` file** — copy `.env.example` to `.env` and add your API key/secret
    2. **Choose a strategy** — start with `bollinger_bands`
    3. **Set your date range** — defaults to the last 1 year
    4. **Click Run Backtest** — data is fetched from Delta Exchange and cached locally

    ### Available Strategies
    | Strategy | Description |
    |---|---|
    | `bollinger_bands` | Bollinger Bands (mean reversion) + RSI filter |

    > To add a new strategy, create a new `.py` file in the `strategies/` folder implementing `BaseStrategy`.
    """)
