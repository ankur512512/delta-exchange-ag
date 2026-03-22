"""
reports/html_reporter.py — Self-contained HTML backtest report generator.

Generates an interactive HTML report using Plotly charts (embedded inline),
including equity curve, drawdown chart, metrics summary, and trade log table.
"""
import os
import logging
from datetime import datetime
import pytz

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import config
from core.backtest_engine import BacktestResult
from reports.metrics import compute_metrics

logger = logging.getLogger(__name__)


def generate_report(result: BacktestResult, output_dir: str = None) -> str:
    """
    Generate a self-contained HTML report for the backtest result.
    """
    output_dir = output_dir or config.REPORTS_DIR
    os.makedirs(output_dir, exist_ok=True)

    metrics = compute_metrics(
        result.trade_log.closed_trades,
        result.equity_curve,
        result.initial_capital,
        result.timeframe,
    )
    trades_df = result.trade_log.to_dataframe()

    equity_fig     = _build_equity_chart(result.equity_curve, result.initial_capital)
    drawdown_fig   = _build_drawdown_chart(result.equity_curve)
    equity_html    = equity_fig.to_html(full_html=False, include_plotlyjs="cdn")
    drawdown_html  = drawdown_fig.to_html(full_html=False, include_plotlyjs=False)
    metrics_html   = _build_metrics_table(metrics)
    trades_html    = _build_trades_table(trades_df)

    ts   = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    fname = f"report_{result.strategy_name}_{result.timeframe}_{ts}.html"
    fpath = os.path.join(output_dir, fname)

    html = _render_page(
        strategy_name=result.strategy_name,
        symbol=result.symbol,
        timeframe=result.timeframe,
        start_date=result.start_date,
        end_date=result.end_date,
        metrics=metrics,
        equity_html=equity_html,
        drawdown_html=drawdown_html,
        metrics_html=metrics_html,
        trades_html=trades_html,
    )

    with open(fpath, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"HTML report saved → {fpath}")
    return fpath


def _build_equity_chart(equity: pd.Series, initial_capital: float) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=equity.index, y=equity.values,
        mode="lines", name="Portfolio Value",
        line=dict(color="#00d4aa", width=2),
        fill="tozeroy", fillcolor="rgba(0, 212, 170, 0.08)",
    ))
    fig.add_hline(
        y=initial_capital, line_dash="dash",
        line_color="rgba(255,255,255,0.3)",
        annotation_text="Initial Capital",
    )
    fig.update_layout(
        title="Equity Curve",
        xaxis_title="Date", yaxis_title="Portfolio Value (USD)",
        template="plotly_dark",
        paper_bgcolor="#0f1117", plot_bgcolor="#0f1117",
        hovermode="x unified",
        margin=dict(l=50, r=20, t=50, b=40),
        height=400,
    )
    return fig


def _build_drawdown_chart(equity: pd.Series) -> go.Figure:
    if equity.empty:
        return go.Figure()
    rolling_max = equity.cummax()
    drawdown    = (equity - rolling_max) / rolling_max * 100
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=drawdown.index, y=drawdown.values,
        mode="lines", name="Drawdown %",
        line=dict(color="#ff4d6d", width=1.5),
        fill="tozeroy", fillcolor="rgba(255, 77, 109, 0.12)",
    ))
    fig.update_layout(
        title="Drawdown (%)",
        xaxis_title="Date", yaxis_title="Drawdown (%)",
        template="plotly_dark",
        paper_bgcolor="#0f1117", plot_bgcolor="#0f1117",
        hovermode="x unified",
        margin=dict(l=50, r=20, t=50, b=40),
        height=300,
    )
    return fig


def _build_metrics_table(metrics: dict) -> str:
    sections = {
        "Overview": [
            ("Total Trades",          metrics["total_trades"]),
            ("Winning Trades",        metrics["winning_trades"]),
            ("Losing Trades",         metrics["losing_trades"]),
            ("Win Rate",              f"{metrics['win_rate_pct']}%"),
            ("Profit Factor",         metrics["profit_factor"]),
        ],
        "P&L": [
            ("Initial Capital",       f"${metrics['initial_capital']:,.2f}"),
            ("Final Capital",         f"${metrics['final_capital']:,.2f}"),
            ("Total P&L",             f"${metrics['total_pnl']:,.2f}"),
            ("Total Return",          f"{metrics['total_return_pct']}%"),
            ("Annualised Return",     f"{metrics['annualised_return_pct']}%"),
        ],
        "Per-Trade Stats": [
            ("Avg Trade P&L",         f"${metrics['avg_trade_pnl']:,.2f}"),
            ("Avg Winner",            f"${metrics['avg_winner']:,.2f}"),
            ("Avg Loser",             f"${metrics['avg_loser']:,.2f}"),
            ("Avg Holding Period",    f"{metrics['avg_holding_hours']}h"),
        ],
        "Risk": [
            ("Max Drawdown (USD)",    f"${metrics['max_drawdown_usd']:,.2f}"),
            ("Max Drawdown (%)",      f"{metrics['max_drawdown_pct']}%"),
            ("Max DD Duration",       f"{metrics['max_drawdown_duration_candles']} candles"),
            ("Sharpe Ratio",          metrics["sharpe_ratio"]),
            ("Max Consec. Wins",      metrics["max_consecutive_wins"]),
            ("Max Consec. Losses",    metrics["max_consecutive_losses"]),
        ],
    }
    html = ""
    for section, rows in sections.items():
        html += f'<h4 class="section-title">{section}</h4><table class="metrics-table">'
        for label, value in rows:
            color_class = ""
            if isinstance(value, str) and value.startswith("$"):
                num = float(value.replace("$", "").replace(",", "").replace("%", "") or 0)
                color_class = "positive" if num > 0 else ("negative" if num < 0 else "")
            html += f'<tr><td class="label">{label}</td><td class="value {color_class}">{value}</td></tr>'
        html += "</table>"
    return html


def _build_trades_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "<p>No trades executed.</p>"
    cols = ["trade_id", "side", "entry_time", "entry_price", "exit_time",
            "exit_price", "pnl", "pnl_pct", "exit_reason", "holding_hours"]
    cols = [c for c in cols if c in df.columns]
    display = df[cols].copy()
    if "pnl" in display.columns:
        display["pnl"] = display["pnl"].apply(lambda x: f"${x:,.2f}")
    if "pnl_pct" in display.columns:
        display["pnl_pct"] = display["pnl_pct"].apply(lambda x: f"{x:.2f}%")
    if "entry_price" in display.columns:
        display["entry_price"] = display["entry_price"].apply(lambda x: f"{x:,.2f}")
    if "exit_price" in display.columns:
        display["exit_price"] = display["exit_price"].apply(lambda x: f"{x:,.2f}" if x else "-")
    display.columns = [c.replace("_", " ").title() for c in display.columns]
    return display.to_html(index=False, classes="trades-table", border=0)


def _render_page(
    strategy_name, symbol, timeframe, start_date, end_date,
    metrics, equity_html, drawdown_html, metrics_html, trades_html
) -> str:
    ist_now = datetime.now(pytz.timezone("Asia/Kolkata"))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Backtest Report — {strategy_name} {symbol} {timeframe}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Inter', 'Segoe UI', sans-serif; background: #0f1117; color: #e0e0e0; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
  header {{ background: linear-gradient(135deg, #1a1d2e 0%, #0f1117 100%);
             border-bottom: 1px solid #2d2f3e; padding: 32px 24px 24px; margin-bottom: 32px; }}
  header h1 {{ font-size: 28px; font-weight: 700; color: #fff; }}
  header p {{ color: #888; margin-top: 6px; font-size: 14px; }}
  .kpi-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
               gap: 16px; margin-bottom: 32px; }}
  .kpi-card {{ background: #1a1d2e; border: 1px solid #2d2f3e; border-radius: 12px;
               padding: 20px; text-align: center; }}
  .kpi-card .label {{ font-size: 12px; color: #888; text-transform: uppercase;
                       letter-spacing: 0.08em; margin-bottom: 8px; }}
  .kpi-card .value {{ font-size: 26px; font-weight: 700; color: #fff; }}
  .kpi-card .value.pos {{ color: #00d4aa; }}
  .kpi-card .value.neg {{ color: #ff4d6d; }}
  .card {{ background: #1a1d2e; border: 1px solid #2d2f3e; border-radius: 12px;
             padding: 24px; margin-bottom: 24px; }}
  .card h3 {{ font-size: 16px; font-weight: 600; color: #fff; margin-bottom: 16px; }}
  .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 24px; }}
  .section-title {{ color: #888; font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em;
                     margin-bottom: 8px; margin-top: 16px; }}
  .section-title:first-child {{ margin-top: 0; }}
  .metrics-table {{ width: 100%; border-collapse: collapse; }}
  .metrics-table td {{ padding: 7px 4px; border-bottom: 1px solid #23253a; font-size: 13px; }}
  .metrics-table .label {{ color: #aaa; }}
  .metrics-table .value {{ text-align: right; font-weight: 600; color: #fff; }}
  .metrics-table .positive {{ color: #00d4aa; }}
  .metrics-table .negative {{ color: #ff4d6d; }}
  .trades-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  .trades-table th {{ padding: 10px 8px; background: #23253a; color: #aaa;
                       text-align: left; font-weight: 600; font-size: 11px;
                       text-transform: uppercase; letter-spacing: 0.05em; }}
  .trades-table td {{ padding: 9px 8px; border-bottom: 1px solid #1f2133; color: #e0e0e0; }}
  .trades-table tr:hover td {{ background: #1f2133; }}
  .overflow-x {{ overflow-x: auto; }}
  footer {{ text-align: center; color: #444; font-size: 12px; padding: 32px 0 16px; }}
</style>
</head>
<body>
<header>
  <div class="container">
    <h1>📈 Backtest Report</h1>
    <p>{strategy_name.replace("_", " ").title()} &nbsp;·&nbsp; {symbol} {timeframe} &nbsp;·&nbsp; {start_date} → {end_date} (IST)</p>
  </div>
</header>
<div class="container">
  <div class="kpi-row">
    <div class="kpi-card"><div class="label">Total Return</div><div class="value {'pos' if metrics['total_return_pct'] >= 0 else 'neg'}">{metrics['total_return_pct']}%</div></div>
    <div class="kpi-card"><div class="label">Total P&amp;L</div><div class="value {'pos' if metrics['total_pnl'] >= 0 else 'neg'}">${metrics['total_pnl']:,.2f}</div></div>
    <div class="kpi-card"><div class="label">Win Rate</div><div class="value">{metrics['win_rate_pct']}%</div></div>
    <div class="kpi-card"><div class="label">Sharpe Ratio</div><div class="value">{metrics['sharpe_ratio']}</div></div>
    <div class="kpi-card"><div class="label">Max Drawdown</div><div class="value neg">{metrics['max_drawdown_pct']}%</div></div>
    <div class="kpi-card"><div class="label">Total Trades</div><div class="value">{metrics['total_trades']}</div></div>
  </div>
  <div class="card"><h3>Equity Curve</h3>{equity_html}</div>
  <div class="card"><h3>Drawdown</h3>{drawdown_html}</div>
  <div class="card"><h3>Performance Metrics</h3><div class="metrics-grid">{metrics_html}</div></div>
  <div class="card"><h3>Trade Log</h3><div class="overflow-x">{trades_html}</div></div>
</div>
<footer>Generated {ist_now.strftime("%Y-%m-%d %H:%M")} IST by Delta Antigravity</footer>
</body>
</html>"""
