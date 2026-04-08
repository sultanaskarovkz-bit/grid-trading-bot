"""
Event-driven backtesting engine.
Iterates bar-by-bar, feeds data to the strategy, tracks equity and statistics.
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from config import AppConfig, GridConfig
from data_manager import DataManager
from indicators import compute_indicators, correlation_matrix
from risk_manager import RiskManager
from strategy import GridStrategy

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Complete backtest output with statistics."""
    equity_curve: pd.Series
    trade_log: list
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    calmar_ratio: float = 0.0
    total_trades: int = 0
    win_rate: float = 0.0
    avg_trade_pnl: float = 0.0
    avg_holding_hours: float = 0.0
    max_consecutive_losses: int = 0
    monthly_returns: pd.Series = field(default_factory=pd.Series)

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "BACKTEST RESULTS",
            "=" * 60,
            f"Total Return:          {self.total_return_pct:>10.2f}%",
            f"Max Drawdown:          {self.max_drawdown_pct:>10.2f}%",
            f"Sharpe Ratio:          {self.sharpe_ratio:>10.2f}",
            f"Profit Factor:         {self.profit_factor:>10.2f}",
            f"Calmar Ratio:          {self.calmar_ratio:>10.2f}",
            f"Total Basket Trades:   {self.total_trades:>10d}",
            f"Win Rate:              {self.win_rate:>10.1f}%",
            f"Avg Trade PnL:         {self.avg_trade_pnl:>10.2f}",
            f"Avg Holding (hours):   {self.avg_holding_hours:>10.1f}",
            f"Max Consec. Losses:    {self.max_consecutive_losses:>10d}",
            "=" * 60,
        ]
        return "\n".join(lines)


class BacktestEngine:
    """Runs the strategy on historical data bar-by-bar."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.grid_config = config.grid
        self.bt_config = config.backtest

    def run(self, data: dict[str, pd.DataFrame]) -> BacktestResult:
        """
        Execute backtest.
        data: {symbol: DataFrame with OHLCV columns}
        """
        pairs = self.config.get_enabled_pairs()

        # Compute indicators for each pair
        prepared_data = {}
        for pair in pairs:
            if pair.symbol not in data:
                continue
            df = compute_indicators(
                data[pair.symbol],
                atr_period=self.grid_config.atr_period,
                ema_fast=self.grid_config.ema_fast,
                ema_slow=self.grid_config.ema_slow,
            )
            prepared_data[pair.symbol] = df

        if not prepared_data:
            logger.error("No data available for any pair")
            return self._empty_result()

        # Align to common index
        common_index = None
        for df in prepared_data.values():
            idx = df.index
            if common_index is None:
                common_index = idx
            else:
                common_index = common_index.intersection(idx)

        if common_index is None or len(common_index) == 0:
            logger.error("No common data between pairs after alignment")
            return self._empty_result()

        for symbol in prepared_data:
            prepared_data[symbol] = prepared_data[symbol].loc[common_index]

        # Initialize components
        risk_manager = RiskManager(self.grid_config, pairs)
        strategy = GridStrategy(
            self.grid_config, risk_manager, pairs,
            commission_per_lot=self.bt_config.commission_per_lot,
        )

        equity = self.bt_config.initial_equity
        risk_manager.update_peak_equity(equity)
        equity_history = []
        all_actions = []

        # Pre-compute correlation matrix (recompute periodically)
        corr_matrix = None
        corr_recompute_interval = 24  # bars
        symbols = list(prepared_data.keys())

        total_bars = len(common_index)
        logger.info(f"Running backtest: {total_bars} bars, {len(symbols)} pairs")

        for bar_idx, timestamp in enumerate(common_index):
            # Build price dict for this bar
            prices = {}
            for symbol in symbols:
                row = prepared_data[symbol].loc[timestamp]
                prices[symbol] = {
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "atr": row.get("atr", np.nan),
                    "trend": row.get("trend", 0),
                }

            # Recompute correlation periodically
            if bar_idx % corr_recompute_interval == 0 and len(symbols) > 1:
                close_dict = {}
                for symbol in symbols:
                    end_idx = min(bar_idx + 1, total_bars)
                    start_idx = max(0, end_idx - self.grid_config.correlation_window)
                    close_dict[symbol] = prepared_data[symbol].iloc[start_idx:end_idx]["close"]
                if all(len(v) > 10 for v in close_dict.values()):
                    corr_matrix = correlation_matrix(
                        close_dict, self.grid_config.correlation_window
                    )

            # Pass realized equity; strategy computes unrealized internally
            actions = strategy.on_bar(timestamp, prices, equity, corr_matrix)

            # Process actions
            for action in actions:
                if action["action"] == "open":
                    equity -= action["commission"]
                elif action["action"] == "close_basket":
                    equity += action["pnl"]

                all_actions.append(action)

            # Track equity (including unrealized)
            unrealized = sum(
                state.basket_pnl
                for state in strategy.pair_states.values()
                if state.has_positions
            )
            equity_history.append({
                "datetime": timestamp,
                "equity": equity + unrealized,
                "realized_equity": equity,
            })

        # Force close remaining positions
        if any(s.has_positions for s in strategy.pair_states.values()):
            last_ts = common_index[-1]
            last_prices = {}
            for symbol in symbols:
                row = prepared_data[symbol].iloc[-1]
                last_prices[symbol] = {"close": row["close"]}
            close_actions = strategy._close_all_baskets(last_ts, last_prices, "END_OF_TEST")
            for action in close_actions:
                if action["action"] == "close_basket":
                    equity += action["pnl"]
                all_actions.append(action)

        # Build result
        eq_df = pd.DataFrame(equity_history).set_index("datetime")
        equity_curve = eq_df["equity"]

        # Update trade records with final equity
        for trade in strategy.trade_history:
            trade.equity_after = equity

        return self._compute_statistics(
            equity_curve, strategy.trade_history,
            self.bt_config.initial_equity, all_actions
        )

    def _compute_statistics(self, equity_curve: pd.Series,
                            trades: list, initial_equity: float,
                            actions: list) -> BacktestResult:
        """Compute all performance metrics."""
        result = BacktestResult(
            equity_curve=equity_curve,
            trade_log=actions,
        )

        if equity_curve.empty:
            return result

        final_equity = equity_curve.iloc[-1]
        result.total_return_pct = (final_equity / initial_equity - 1) * 100

        # Max drawdown
        running_max = equity_curve.cummax()
        drawdown = (equity_curve - running_max) / running_max * 100
        result.max_drawdown_pct = abs(drawdown.min())

        # Sharpe ratio (annualized, assuming hourly bars)
        returns = equity_curve.pct_change().dropna()
        if len(returns) > 1 and returns.std() > 0:
            # ~252 trading days * ~24 hours for forex
            periods_per_year = 252 * 24
            result.sharpe_ratio = (
                returns.mean() / returns.std() * np.sqrt(periods_per_year)
            )

        # Profit factor
        if trades:
            wins = [t.pnl for t in trades if t.pnl > 0]
            losses = [t.pnl for t in trades if t.pnl < 0]
            total_wins = sum(wins) if wins else 0
            total_losses = abs(sum(losses)) if losses else 0
            result.profit_factor = (
                total_wins / total_losses if total_losses > 0 else float("inf")
            )

            result.total_trades = len(trades)
            result.win_rate = len(wins) / len(trades) * 100 if trades else 0
            result.avg_trade_pnl = np.mean([t.pnl for t in trades])
            result.avg_holding_hours = np.mean([t.holding_time_hours for t in trades])

            # Max consecutive losses
            max_consec = 0
            current_consec = 0
            for t in trades:
                if t.pnl < 0:
                    current_consec += 1
                    max_consec = max(max_consec, current_consec)
                else:
                    current_consec = 0
            result.max_consecutive_losses = max_consec

        # Calmar ratio
        if result.max_drawdown_pct > 0:
            # Annualize return
            n_bars = len(equity_curve)
            years = n_bars / (252 * 24) if n_bars > 0 else 1
            annual_return = result.total_return_pct / years if years > 0 else 0
            result.calmar_ratio = annual_return / result.max_drawdown_pct

        # Monthly returns
        if not equity_curve.empty:
            monthly = equity_curve.resample("ME").last()
            result.monthly_returns = monthly.pct_change().dropna() * 100

        return result

    def _empty_result(self) -> BacktestResult:
        return BacktestResult(
            equity_curve=pd.Series(dtype=float),
            trade_log=[],
        )
