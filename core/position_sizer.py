"""
core/position_sizer.py — Dynamic position sizing based on fixed-risk rule.

Formula:
    position_size = (portfolio_value × max_risk_pct) / |entry_price - stop_loss_price|

This ensures that if the stop-loss is hit, the portfolio loses exactly
max_risk_pct (default 0.3%) of its current value — no more.
"""
import logging
import config

logger = logging.getLogger(__name__)

# Minimum contract size on Delta Exchange for BTCUSD (in BTC)
# Delta Exchange uses integer contracts where 1 contract = $1 of BTC notional
# For BTCUSD perpetual: size is in USD contracts (1 contract = $1 USD notional)
# We'll keep position size in float USD and let the caller round to contract size.
MIN_CONTRACT_SIZE = 1  # USD contract minimum


class PositionSizer:
    """
    Calculates trade size such that a stop-loss hit costs at most
    `max_risk_pct` of the current portfolio value.

    Example:
        Portfolio: $10,000
        Risk per trade: 0.3% → $30 max loss
        Entry: $70,000 BTC, Stop-loss: $69,300 BTC (700 USD away)
        Position size = $30 / $700 = 0.0428 BTC
        Notional = 0.0428 × $70,000 = ~$3,000
    """

    def __init__(
        self,
        portfolio_value: float = None,
        max_risk_pct: float = None,
    ):
        self.portfolio_value = portfolio_value or config.INITIAL_CAPITAL
        self.max_risk_pct    = max_risk_pct or config.MAX_RISK_PER_TRADE

    def update_portfolio(self, new_value: float):
        """Update the reference portfolio value after each trade."""
        self.portfolio_value = new_value

    def calculate_size(
        self,
        entry_price: float,
        stop_loss_price: float,
        symbol: str = "BTCUSD",
    ) -> float:
        """
        Calculate position size in BTC such that stop-loss hit = max_risk_pct of portfolio.

        Args:
            entry_price:     Planned trade entry price in USD
            stop_loss_price: Stop-loss price in USD
            symbol:          Trading symbol (for future multi-symbol support)

        Returns:
            Position size in BTC (float). Caller should round to exchange precision.
            Returns 0.0 if the risk parameters make the trade impossible.
        """
        risk_usd = self.portfolio_value * self.max_risk_pct
        price_diff = abs(entry_price - stop_loss_price)

        if price_diff <= 0:
            logger.warning(
                "Entry price equals stop-loss price — cannot size position. Returning 0."
            )
            return 0.0

        size_btc = risk_usd / price_diff

        logger.debug(
            f"Position sizing: portfolio=${self.portfolio_value:,.2f}, "
            f"risk={self.max_risk_pct*100:.2f}% (${risk_usd:.2f}), "
            f"entry={entry_price}, SL={stop_loss_price}, "
            f"diff={price_diff:.2f} → size={size_btc:.6f} BTC"
        )

        return round(size_btc, 6)

    def dollar_risk(self) -> float:
        """Maximum dollar loss allowed per trade given current portfolio."""
        return self.portfolio_value * self.max_risk_pct

    def suggested_stop_loss(
        self,
        entry_price: float,
        side: str,
        atr: float,
        atr_multiplier: float = 1.5,
    ) -> float:
        """
        Suggest a stop-loss price based on ATR (Average True Range).
        Uses ATR × multiplier as the distance from entry.

        Args:
            entry_price:    Entry price in USD
            side:           "long" or "short"
            atr:            Current ATR value
            atr_multiplier: How many ATRs away to place the stop

        Returns:
            Suggested stop-loss price in USD.
        """
        distance = atr * atr_multiplier
        if side == "long":
            return round(entry_price - distance, 2)
        else:
            return round(entry_price + distance, 2)
