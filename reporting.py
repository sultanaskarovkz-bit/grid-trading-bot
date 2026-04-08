"""
Reporting and visualization module.
Generates equity curves, drawdown charts, monthly heatmaps, and statistics.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from backtester import BacktestResult

logger = logging.getLogger(__name__)


class Reporter:
    """Generates visual reports from backtest results."""

    def __init__(self, result: BacktestResult, output_dir: str = "reports"):
        self.result = result
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def plot_equity_curve(self, show: bool = True) -> None:
        """Equity curve with drawdown overlay."""
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8),
                                        gridspec_kw={"height_ratios": [3, 1]},
                                        sharex=True)

        equity = self.result.equity_curve

        # Equity line
        ax1.plot(equity.index, equity.values, color="#2196F3", linewidth=1.2,
                 label="Equity")
        ax1.fill_between(equity.index, equity.values, alpha=0.1, color="#2196F3")
        ax1.set_ylabel("Equity ($)")
        ax1.set_title("Equity Curve", fontsize=14, fontweight="bold")
        ax1.legend(loc="upper left")
        ax1.grid(True, alpha=0.3)

        # Drawdown
        running_max = equity.cummax()
        drawdown = (equity - running_max) / running_max * 100
        ax2.fill_between(drawdown.index, drawdown.values, 0,
                         color="#F44336", alpha=0.4)
        ax2.set_ylabel("Drawdown (%)")
        ax2.set_xlabel("Date")
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(self.output_dir / "equity_curve.png", dpi=150, bbox_inches="tight")
        if show:
            plt.show()
        plt.close()

    def plot_monthly_returns(self, show: bool = True) -> None:
        """Monthly returns heatmap."""
        if self.result.monthly_returns.empty:
            logger.warning("No monthly returns to plot")
            return

        equity = self.result.equity_curve
        monthly = equity.resample("ME").last()
        monthly_ret = monthly.pct_change().dropna() * 100

        # Build year x month matrix
        years = sorted(set(monthly_ret.index.year))
        months = range(1, 13)
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        data = np.full((len(years), 12), np.nan)
        for date, ret in monthly_ret.items():
            y_idx = years.index(date.year)
            m_idx = date.month - 1
            data[y_idx, m_idx] = ret

        fig, ax = plt.subplots(figsize=(14, max(4, len(years) * 0.8)))
        im = ax.imshow(data, cmap="RdYlGn", aspect="auto",
                       vmin=-10, vmax=10)

        ax.set_xticks(range(12))
        ax.set_xticklabels(month_names)
        ax.set_yticks(range(len(years)))
        ax.set_yticklabels(years)

        # Add text annotations
        for i in range(len(years)):
            for j in range(12):
                if not np.isnan(data[i, j]):
                    color = "white" if abs(data[i, j]) > 5 else "black"
                    ax.text(j, i, f"{data[i, j]:.1f}%", ha="center", va="center",
                            fontsize=8, color=color)

        plt.colorbar(im, ax=ax, label="Return (%)")
        ax.set_title("Monthly Returns Heatmap", fontsize=14, fontweight="bold")

        plt.tight_layout()
        plt.savefig(self.output_dir / "monthly_returns.png", dpi=150, bbox_inches="tight")
        if show:
            plt.show()
        plt.close()

    def plot_trade_distribution(self, show: bool = True) -> None:
        """Histogram of basket trade P&L."""
        if not self.result.trade_log:
            return

        # Extract basket close P&L
        basket_pnls = [
            a["pnl"] for a in self.result.trade_log
            if a.get("action") == "close_basket"
        ]

        if not basket_pnls:
            return

        fig, ax = plt.subplots(figsize=(10, 6))

        colors = ["#4CAF50" if p >= 0 else "#F44336" for p in basket_pnls]
        ax.bar(range(len(basket_pnls)), basket_pnls, color=colors, alpha=0.7)
        ax.axhline(y=0, color="gray", linestyle="--", linewidth=0.8)
        ax.set_xlabel("Trade #")
        ax.set_ylabel("P&L ($)")
        ax.set_title("Basket Trade P&L Distribution", fontsize=14, fontweight="bold")
        ax.grid(True, alpha=0.3, axis="y")

        plt.tight_layout()
        plt.savefig(self.output_dir / "trade_distribution.png", dpi=150, bbox_inches="tight")
        if show:
            plt.show()
        plt.close()

    def plot_pair_contribution(self, show: bool = True) -> None:
        """Per-pair P&L contribution."""
        if not self.result.trade_log:
            return

        pair_pnl = {}
        for action in self.result.trade_log:
            if action.get("action") == "close_basket":
                symbol = action["symbol"]
                pair_pnl[symbol] = pair_pnl.get(symbol, 0) + action["pnl"]

        if not pair_pnl:
            return

        fig, ax = plt.subplots(figsize=(10, 6))

        symbols = list(pair_pnl.keys())
        pnls = [pair_pnl[s] for s in symbols]
        colors = ["#4CAF50" if p >= 0 else "#F44336" for p in pnls]

        bars = ax.bar(symbols, pnls, color=colors, alpha=0.8, edgecolor="white")

        for bar, pnl in zip(bars, pnls):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                    f"${pnl:.0f}", ha="center", va="bottom", fontsize=10)

        ax.axhline(y=0, color="gray", linestyle="--", linewidth=0.8)
        ax.set_ylabel("Total P&L ($)")
        ax.set_title("P&L by Currency Pair", fontsize=14, fontweight="bold")
        ax.grid(True, alpha=0.3, axis="y")

        plt.tight_layout()
        plt.savefig(self.output_dir / "pair_contribution.png", dpi=150, bbox_inches="tight")
        if show:
            plt.show()
        plt.close()

    def print_summary(self) -> None:
        """Print statistics to console."""
        print(self.result.summary())

    def export_csv(self) -> None:
        """Export equity curve and trade log."""
        self.result.equity_curve.to_csv(self.output_dir / "equity_curve.csv")

        if self.result.trade_log:
            trades_df = pd.DataFrame(self.result.trade_log)
            trades_df.to_csv(self.output_dir / "trade_log.csv", index=False)

        logger.info(f"CSV exported to {self.output_dir}")

    def generate_full_report(self, show: bool = True) -> None:
        """Generate all charts and export data."""
        self.print_summary()
        self.plot_equity_curve(show=show)
        self.plot_monthly_returns(show=show)
        self.plot_trade_distribution(show=show)
        self.plot_pair_contribution(show=show)
        self.export_csv()
        logger.info(f"Full report saved to {self.output_dir}/")
