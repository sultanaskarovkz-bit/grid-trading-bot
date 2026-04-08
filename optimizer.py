"""
Optuna-based parameter optimization for the grid trading strategy.
Uses Bayesian optimization (TPE sampler) to find optimal parameter combinations.
"""

import copy
import logging

import optuna
import pandas as pd

from config import AppConfig, GridConfig
from backtester import BacktestEngine

logger = logging.getLogger(__name__)

# Parameter search space
PARAM_SPACE = {
    "base_grid_distance_pips": (10.0, 60.0),
    "grid_distance_multiplier": (1.1, 2.5),
    "lot_multiplier": (1.1, 2.5),
    "atr_multiplier": (0.5, 3.0),
    "fix_take_profit_pct": (0.5, 5.0),
    "stop_drawdown_pct": (5.0, 30.0),
    "ema_fast": (20, 100),
    "ema_slow": (100, 400),
    "correlation_threshold": (0.6, 0.95),
    "risk_per_trade_pct": (0.5, 3.0),
    "base_time_delay_seconds": (900, 7200),
    "max_grid_levels": (4, 12),
}


class GridOptimizer:
    """Optimizes grid strategy parameters using Optuna."""

    def __init__(self, config: AppConfig, data: dict[str, pd.DataFrame]):
        self.base_config = config
        self.data = data  # cached, loaded once

    def _sample_params(self, trial: optuna.Trial) -> GridConfig:
        """Sample a GridConfig from the search space."""
        config = copy.deepcopy(self.base_config.grid)

        config.base_grid_distance_pips = trial.suggest_float(
            "base_grid_distance_pips", *PARAM_SPACE["base_grid_distance_pips"]
        )
        config.grid_distance_multiplier = trial.suggest_float(
            "grid_distance_multiplier", *PARAM_SPACE["grid_distance_multiplier"]
        )
        config.lot_multiplier = trial.suggest_float(
            "lot_multiplier", *PARAM_SPACE["lot_multiplier"]
        )
        config.atr_multiplier = trial.suggest_float(
            "atr_multiplier", *PARAM_SPACE["atr_multiplier"]
        )
        config.fix_take_profit_pct = trial.suggest_float(
            "fix_take_profit_pct", *PARAM_SPACE["fix_take_profit_pct"]
        )
        config.stop_drawdown_pct = trial.suggest_float(
            "stop_drawdown_pct", *PARAM_SPACE["stop_drawdown_pct"]
        )
        config.ema_fast = trial.suggest_int(
            "ema_fast", *PARAM_SPACE["ema_fast"]
        )
        config.ema_slow = trial.suggest_int(
            "ema_slow", *PARAM_SPACE["ema_slow"]
        )
        config.correlation_threshold = trial.suggest_float(
            "correlation_threshold", *PARAM_SPACE["correlation_threshold"]
        )
        config.risk_per_trade_pct = trial.suggest_float(
            "risk_per_trade_pct", *PARAM_SPACE["risk_per_trade_pct"]
        )
        config.base_time_delay_seconds = trial.suggest_int(
            "base_time_delay_seconds", *PARAM_SPACE["base_time_delay_seconds"],
            step=300,
        )
        config.max_grid_levels = trial.suggest_int(
            "max_grid_levels", *PARAM_SPACE["max_grid_levels"]
        )

        # Ensure ema_fast < ema_slow
        if config.ema_fast >= config.ema_slow:
            config.ema_slow = config.ema_fast + 50

        return config

    def objective(self, trial: optuna.Trial) -> float:
        """Single optimization trial."""
        grid_config = self._sample_params(trial)

        trial_config = copy.deepcopy(self.base_config)
        trial_config.grid = grid_config

        engine = BacktestEngine(trial_config)
        result = engine.run(self.data)

        # Report intermediate metrics
        trial.set_user_attr("total_return_pct", result.total_return_pct)
        trial.set_user_attr("max_drawdown_pct", result.max_drawdown_pct)
        trial.set_user_attr("sharpe_ratio", result.sharpe_ratio)
        trial.set_user_attr("profit_factor", result.profit_factor)
        trial.set_user_attr("total_trades", result.total_trades)
        trial.set_user_attr("win_rate", result.win_rate)

        # Select metric to optimize
        metric = self.base_config.optimizer.metric
        if metric == "sharpe_ratio":
            return result.sharpe_ratio
        elif metric == "profit_factor":
            return result.profit_factor
        elif metric == "calmar_ratio":
            return result.calmar_ratio
        else:
            return result.sharpe_ratio

    def optimize(self) -> optuna.Study:
        """Run optimization."""
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        study = optuna.create_study(
            study_name=self.base_config.optimizer.study_name,
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=42),
            pruner=optuna.pruners.MedianPruner(),
        )

        n_trials = self.base_config.optimizer.n_trials
        logger.info(f"Starting optimization: {n_trials} trials")

        study.optimize(
            self.objective,
            n_trials=n_trials,
            n_jobs=self.base_config.optimizer.n_jobs,
            show_progress_bar=True,
        )

        logger.info(f"Best trial: {study.best_trial.number}")
        logger.info(f"Best value: {study.best_value:.4f}")
        logger.info(f"Best params: {study.best_params}")

        return study

    def best_config(self, study: optuna.Study) -> GridConfig:
        """Extract best parameters into a GridConfig."""
        config = copy.deepcopy(self.base_config.grid)
        best = study.best_params

        for key, value in best.items():
            if hasattr(config, key):
                setattr(config, key, value)

        if config.ema_fast >= config.ema_slow:
            config.ema_slow = config.ema_fast + 50

        return config

    @staticmethod
    def print_importance(study: optuna.Study) -> None:
        """Print parameter importance ranking."""
        try:
            importance = optuna.importance.get_param_importances(study)
            print("\nParameter Importance:")
            print("-" * 40)
            for param, imp in sorted(importance.items(), key=lambda x: -x[1]):
                bar = "#" * int(imp * 40)
                print(f"  {param:<30s} {imp:.3f} {bar}")
        except Exception as e:
            logger.warning(f"Could not compute importance: {e}")
