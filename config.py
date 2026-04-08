"""
Configuration module for the multi-currency grid trading bot.
All optimizable parameters are defined as dataclass fields for easy Optuna integration.
"""

from dataclasses import dataclass, field
from enum import Enum


class Direction(Enum):
    LONG = "long"
    SHORT = "short"


class Mode(Enum):
    BACKTEST = "backtest"
    OPTIMIZE = "optimize"
    LIVE = "live"


@dataclass
class PairConfig:
    symbol: str
    pip_value: float        # 0.0001 for most, 0.01 for JPY pairs
    spread_pips: float      # typical spread in pips
    min_lot: float = 0.01
    max_lot: float = 10.0
    contract_size: float = 100_000.0  # standard lot
    enabled: bool = True


@dataclass
class GridConfig:
    # Grid structure
    base_grid_distance_pips: float = 30.0
    grid_distance_multiplier: float = 1.4
    base_lot_size: float = 0.01
    lot_multiplier: float = 1.3
    max_grid_levels: int = 6

    # Time delays between grid levels (seconds)
    # Level 0: immediate, Level 1: 30min, Level 2: 1h, Level 3: 2h, Level 4: 4h, ...
    base_time_delay_seconds: int = 1800  # 30 minutes base
    time_delay_multiplier: float = 2.0   # each level doubles

    # ATR-adaptive spacing
    atr_period: int = 14
    atr_multiplier: float = 1.0  # scales ATR into grid distance

    # Basket take profit (% of equity across ALL pairs)
    fix_take_profit_pct: float = 2.0

    # Drawdown limits
    stop_drawdown_pct: float = 10.0       # stops new orders
    max_portfolio_drawdown_pct: float = 20.0  # hard stop-loss for entire portfolio

    # Trend filter (EMA crossover)
    trend_filter_enabled: bool = True
    ema_fast: int = 50
    ema_slow: int = 200

    # Correlation filter
    correlation_filter_enabled: bool = True
    correlation_window: int = 100
    correlation_threshold: float = 0.85
    max_correlated_positions: int = 2

    # Session filter (UTC hours)
    session_filter_enabled: bool = True
    session_start_utc: int = 7    # London open
    session_end_utc: int = 21     # NY close

    # Dynamic lot sizing
    dynamic_lot_enabled: bool = True
    risk_per_trade_pct: float = 1.0
    equity_base: float = 10_000.0

    # Cooldown after stops
    base_cooldown_hours: int = 2
    max_cooldown_hours: int = 24
    max_simultaneous_pairs: int = 5

    # Timezone offset from UTC (Moscow = 3)
    timezone_offset_utc: int = 3

    def __post_init__(self):
        """Validate parameters after initialization."""
        if self.ema_fast >= self.ema_slow:
            self.ema_fast, self.ema_slow = min(self.ema_fast, self.ema_slow), max(self.ema_fast, self.ema_slow)
        if self.base_grid_distance_pips <= 0:
            self.base_grid_distance_pips = 30.0
        if self.lot_multiplier < 1.0:
            self.lot_multiplier = 1.0
        if self.grid_distance_multiplier < 1.0:
            self.grid_distance_multiplier = 1.0
        if self.max_grid_levels < 1:
            self.max_grid_levels = 1
        if self.fix_take_profit_pct <= 0:
            self.fix_take_profit_pct = 1.0
        if self.stop_drawdown_pct <= 0:
            self.stop_drawdown_pct = 10.0
        if self.max_portfolio_drawdown_pct <= self.stop_drawdown_pct:
            self.max_portfolio_drawdown_pct = self.stop_drawdown_pct + 5.0
        if self.equity_base <= 0:
            self.equity_base = 10_000.0

    def get_time_delay(self, level: int) -> int:
        """Get required delay in seconds before opening grid level N."""
        if level == 0:
            return 0
        return int(self.base_time_delay_seconds * (self.time_delay_multiplier ** (level - 1)))

    def get_grid_distance_pips(self, level: int) -> float:
        """Get grid distance in pips for level N (from level N-1)."""
        if level == 0:
            return 0.0
        return self.base_grid_distance_pips * (self.grid_distance_multiplier ** (level - 1))

    def get_lot_size(self, level: int, equity: float) -> float:
        """Calculate lot size for grid level N."""
        base = self.base_lot_size
        if self.dynamic_lot_enabled and self.equity_base > 0:
            base *= equity / self.equity_base
        return base * (self.lot_multiplier ** level)


@dataclass
class BacktestConfig:
    start_date: str = "2020-01-01"
    end_date: str = "2025-12-31"
    initial_equity: float = 10_000.0
    commission_per_lot: float = 7.0   # USD round-trip
    timeframe: str = "1h"


@dataclass
class OptimizerConfig:
    n_trials: int = 200
    n_jobs: int = 1
    study_name: str = "grid_bot_optimization"
    metric: str = "calmar_ratio"  # sharpe_ratio, profit_factor, calmar_ratio


@dataclass
class MT5Config:
    server: str = ""
    login: int = 0
    password: str = ""
    timeout: int = 10_000
    path: str = ""


DEFAULT_PAIRS = [
    PairConfig("EURUSD", 0.0001, 1.2),
    PairConfig("GBPUSD", 0.0001, 1.5),
    PairConfig("EURCHF", 0.0001, 2.0),
    PairConfig("EURJPY", 0.01, 1.8),
    PairConfig("USDCHF", 0.0001, 1.8),
    PairConfig("USDJPY", 0.01, 1.5),
]


@dataclass
class AppConfig:
    mode: Mode = Mode.BACKTEST
    grid: GridConfig = field(default_factory=GridConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    optimizer: OptimizerConfig = field(default_factory=OptimizerConfig)
    mt5: MT5Config = field(default_factory=MT5Config)
    pairs: list = field(default_factory=lambda: list(DEFAULT_PAIRS))

    def get_enabled_pairs(self) -> list:
        return [p for p in self.pairs if p.enabled]
