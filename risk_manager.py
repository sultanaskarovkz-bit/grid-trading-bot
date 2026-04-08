"""
Portfolio-level risk management.
Controls drawdown limits, correlation exposure, session filtering, and position sizing.
"""

import logging

import numpy as np
import pandas as pd

from config import GridConfig, PairConfig

logger = logging.getLogger(__name__)


class RiskManager:
    """Central risk gate — decides whether new orders are allowed."""

    def __init__(self, config: GridConfig, pairs: list[PairConfig]):
        self.config = config
        self.pairs = {p.symbol: p for p in pairs}
        self.peak_equity: float = 0.0

    def update_peak_equity(self, equity: float) -> None:
        if equity > self.peak_equity:
            self.peak_equity = equity

    def current_drawdown_pct(self, equity: float) -> float:
        """Current drawdown as percentage from peak."""
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - equity) / self.peak_equity * 100)

    def can_open_new(self, symbol: str, equity: float,
                     current_level: int,
                     timestamp: pd.Timestamp,
                     active_symbols_with_direction: list[tuple[str, str]],
                     correlation_matrix: pd.DataFrame | None = None) -> tuple[bool, str]:
        """
        Master gate for new grid orders.
        Returns (allowed, reason).
        """
        # 1. Max grid levels
        if current_level >= self.config.max_grid_levels:
            return False, f"max grid levels ({self.config.max_grid_levels}) reached"

        # 2. Drawdown check
        dd = self.current_drawdown_pct(equity)
        if dd >= self.config.stop_drawdown_pct:
            return False, f"drawdown {dd:.1f}% >= stop_drawdown {self.config.stop_drawdown_pct}%"

        # 3. Session filter
        if self.config.session_filter_enabled:
            if not self._in_active_session(timestamp):
                return False, "outside active trading session"

        # 4. Correlation filter
        if (self.config.correlation_filter_enabled
                and correlation_matrix is not None
                and current_level == 0):
            if not self._check_correlation(symbol, active_symbols_with_direction,
                                           correlation_matrix):
                return False, "correlated exposure limit reached"

        return True, "ok"

    def check_hard_stop(self, equity: float) -> bool:
        """Returns True if portfolio drawdown exceeds hard stop — close everything."""
        dd = self.current_drawdown_pct(equity)
        return dd >= self.config.max_portfolio_drawdown_pct

    def _in_active_session(self, timestamp: pd.Timestamp) -> bool:
        """Check if current time is within active trading hours (UTC-based)."""
        # Convert to UTC for session check regardless of local timezone
        if timestamp.tzinfo is not None:
            utc_hour = timestamp.utc.hour if hasattr(timestamp, 'utc') else timestamp.hour
            # Use tz_convert to get UTC hour
            try:
                utc_hour = timestamp.tz_convert("UTC").hour
            except Exception:
                utc_hour = timestamp.hour
        else:
            utc_hour = timestamp.hour
        return self.config.session_start_utc <= utc_hour < self.config.session_end_utc

    def _check_correlation(self, symbol: str,
                           active_symbols_with_direction: list[tuple[str, str]],
                           corr_matrix: pd.DataFrame) -> bool:
        """
        Check if opening a position on `symbol` would exceed
        correlated exposure limits.
        """
        if symbol not in corr_matrix.columns:
            return True

        active_symbols = [s for s, _ in active_symbols_with_direction]
        correlated_count = 0

        for active_sym in active_symbols:
            if active_sym not in corr_matrix.columns:
                continue
            corr = abs(corr_matrix.loc[symbol, active_sym])
            if corr >= self.config.correlation_threshold:
                correlated_count += 1

        return correlated_count < self.config.max_correlated_positions

    def calculate_position_size(self, symbol: str, equity: float,
                                grid_level: int, atr_value: float) -> float:
        """
        Calculate lot size considering:
        1. Base lot from config (with level multiplier)
        2. Dynamic scaling from equity
        3. ATR-based risk adjustment
        """
        pair = self.pairs.get(symbol)
        if not pair:
            return self.config.base_lot_size

        lot = self.config.get_lot_size(grid_level, equity)

        # ATR risk adjustment: reduce size in high volatility
        if atr_value > 0 and pair.pip_value > 0:
            typical_atr_pips = 50  # baseline
            current_atr_pips = atr_value / pair.pip_value
            if current_atr_pips > 0.01:  # guard against near-zero ATR
                vol_factor = typical_atr_pips / current_atr_pips
                vol_factor = np.clip(vol_factor, 0.5, 2.0)
                lot *= vol_factor

        lot = max(pair.min_lot, min(lot, pair.max_lot))
        return round(lot, 2)
