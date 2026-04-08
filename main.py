"""
Entry point for the multi-currency grid trading bot.

Usage:
    python main.py backtest                          # Run backtest with defaults
    python main.py backtest --start 2022-01-01       # Custom date range
    python main.py optimize --trials 100             # Optimize parameters
    python main.py optimize --metric sharpe_ratio    # Optimize for Sharpe
    python main.py live --server broker.com --login 12345 --password secret
"""

import argparse
import logging
import sys
from copy import deepcopy

from config import AppConfig, Mode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Multi-Currency Adaptive Grid Trading Bot"
    )
    subparsers = parser.add_subparsers(dest="mode", help="Operating mode")

    # Backtest
    bt = subparsers.add_parser("backtest", help="Run backtesting")
    bt.add_argument("--start", default="2020-01-01", help="Start date")
    bt.add_argument("--end", default="2025-12-31", help="End date")
    bt.add_argument("--equity", type=float, default=10_000, help="Initial equity")
    bt.add_argument("--timeframe", default="1h", help="Timeframe (1h, 4h, 1d)")
    bt.add_argument("--no-show", action="store_true", help="Don't display charts")

    # Optimize
    opt = subparsers.add_parser("optimize", help="Optimize parameters")
    opt.add_argument("--trials", type=int, default=200, help="Number of trials")
    opt.add_argument("--metric", default="calmar_ratio",
                     choices=["sharpe_ratio", "profit_factor", "calmar_ratio"])
    opt.add_argument("--start", default="2020-01-01", help="Start date")
    opt.add_argument("--end", default="2025-12-31", help="End date")
    opt.add_argument("--equity", type=float, default=10_000, help="Initial equity")

    # Signals (real-time analysis + Telegram)
    sg = subparsers.add_parser("signals", help="Real-time signals to Telegram")
    sg.add_argument("--token", default="", help="Telegram bot token")
    sg.add_argument("--chat-id", default="", help="Telegram chat ID")
    sg.add_argument("--equity", type=float, default=10_000, help="Virtual equity")

    # Live
    lv = subparsers.add_parser("live", help="Live trading via MT5")
    lv.add_argument("--server", required=True, help="MT5 server")
    lv.add_argument("--login", type=int, required=True, help="Account login")
    lv.add_argument("--password", required=True, help="Account password")
    lv.add_argument("--path", default="", help="Path to MT5 terminal")
    lv.add_argument("--timeframe", default="1h", help="Timeframe")
    lv.add_argument("--token", default="", help="Telegram bot token")
    lv.add_argument("--chat-id", default="", help="Telegram chat ID")

    return parser.parse_args()


def run_backtest(config: AppConfig, show: bool = True) -> None:
    """Load data, run backtest, generate report."""
    from data_manager import DataManager
    from backtester import BacktestEngine
    from reporting import Reporter

    dm = DataManager()
    symbols = [p.symbol for p in config.get_enabled_pairs()]

    logger.info(f"Loading data for {symbols}...")
    data = dm.load_all_pairs(
        symbols, config.backtest.timeframe,
        config.backtest.start_date, config.backtest.end_date,
    )

    if not data:
        logger.error("No data loaded. Exiting.")
        return

    data = dm.align_data(data)
    logger.info(f"Data loaded: {', '.join(f'{s}: {len(d)} bars' for s, d in data.items())}")

    engine = BacktestEngine(config)
    result = engine.run(data)

    reporter = Reporter(result)
    reporter.generate_full_report(show=show)


def run_optimize(config: AppConfig) -> None:
    """Run parameter optimization, then backtest with best params."""
    from data_manager import DataManager
    from backtester import BacktestEngine
    from optimizer import GridOptimizer
    from reporting import Reporter

    dm = DataManager()
    symbols = [p.symbol for p in config.get_enabled_pairs()]

    logger.info(f"Loading data for optimization...")
    data = dm.load_all_pairs(
        symbols, config.backtest.timeframe,
        config.backtest.start_date, config.backtest.end_date,
    )
    data = dm.align_data(data)

    if not data:
        logger.error("No data loaded. Exiting.")
        return

    optimizer = GridOptimizer(config, data)
    study = optimizer.optimize()

    # Print results
    print("\n" + "=" * 60)
    print("OPTIMIZATION COMPLETE")
    print("=" * 60)
    print(f"Best {config.optimizer.metric}: {study.best_value:.4f}")
    print(f"\nBest Parameters:")
    for param, value in study.best_params.items():
        print(f"  {param}: {value}")

    optimizer.print_importance(study)

    # Run final backtest with best params
    print("\n" + "=" * 60)
    print("FINAL BACKTEST WITH BEST PARAMETERS")
    print("=" * 60)

    best_config = deepcopy(config)
    best_config.grid = optimizer.best_config(study)

    engine = BacktestEngine(best_config)
    result = engine.run(data)

    reporter = Reporter(result, output_dir="reports_optimized")
    reporter.generate_full_report(show=True)

    # Save best config
    _save_best_config(best_config.grid)


def _save_best_config(grid_config) -> None:
    """Save optimized parameters to a file."""
    import json
    from dataclasses import asdict

    params = asdict(grid_config)
    with open("best_config.json", "w") as f:
        json.dump(params, f, indent=2)
    logger.info("Best config saved to best_config.json")


def run_signals(config: AppConfig, token: str = "", chat_id: str = "") -> None:
    """Start real-time signal generator with Telegram notifications."""
    from signal_generator import SignalGenerator
    from telegram_bot import TelegramNotifier

    _load_best_config_if_exists(config)

    telegram = TelegramNotifier(token=token, chat_id=chat_id)

    print("=" * 60)
    print("REAL-TIME SIGNAL MODE")
    print("=" * 60)
    print(f"Pairs: {[p.symbol for p in config.get_enabled_pairs()]}")
    print(f"Telegram: {'ENABLED' if telegram.enabled else 'DISABLED (set --token and --chat-id)'}")
    print(f"Virtual Equity: ${config.backtest.initial_equity:,.0f}")
    print(f"Take Profit: {config.grid.fix_take_profit_pct:.2f}%")
    print(f"Stop Drawdown: {config.grid.stop_drawdown_pct:.1f}%")
    print()
    print("Bot will check market every 5 minutes during active sessions.")
    print("Press Ctrl+C to stop.")
    print("=" * 60)

    generator = SignalGenerator(config, telegram)
    generator.run()


def run_live(config: AppConfig, token: str = "", chat_id: str = "") -> None:
    """Start live trading with optional Telegram notifications."""
    from mt5_connector import MT5Connector, LiveTrader

    _load_best_config_if_exists(config)

    connector = MT5Connector(config.mt5)
    trader = LiveTrader(config, connector)

    print("=" * 60)
    print("LIVE TRADING MODE")
    print("=" * 60)
    print(f"Server: {config.mt5.server}")
    print(f"Pairs: {[p.symbol for p in config.get_enabled_pairs()]}")
    print(f"Stop Drawdown: {config.grid.stop_drawdown_pct}%")
    print(f"Take Profit: {config.grid.fix_take_profit_pct}%")
    print("Press Ctrl+C to stop")
    print("=" * 60)

    trader.run(timeframe=config.backtest.timeframe)


def _load_best_config_if_exists(config: AppConfig) -> None:
    """Load best_config.json into config if it exists."""
    import json
    from pathlib import Path

    config_path = Path("best_config.json")
    if config_path.exists():
        with open(config_path) as f:
            params = json.load(f)
        for key, value in params.items():
            if hasattr(config.grid, key):
                setattr(config.grid, key, value)
        logger.info("Loaded optimized parameters from best_config.json")


def main():
    args = parse_args()

    if not args.mode:
        print("Usage: python main.py {backtest|optimize|signals|live}")
        print("Run 'python main.py signals --help' for options")
        sys.exit(1)

    config = AppConfig()

    if args.mode == "backtest":
        config.mode = Mode.BACKTEST
        config.backtest.start_date = args.start
        config.backtest.end_date = args.end
        config.backtest.initial_equity = args.equity
        config.backtest.timeframe = args.timeframe
        run_backtest(config, show=not args.no_show)

    elif args.mode == "optimize":
        config.mode = Mode.OPTIMIZE
        config.backtest.start_date = args.start
        config.backtest.end_date = args.end
        config.backtest.initial_equity = args.equity
        config.optimizer.n_trials = args.trials
        config.optimizer.metric = args.metric
        run_optimize(config)

    elif args.mode == "signals":
        config.backtest.initial_equity = args.equity
        run_signals(config, token=args.token, chat_id=args.chat_id)

    elif args.mode == "live":
        config.mode = Mode.LIVE
        config.mt5.server = args.server
        config.mt5.login = args.login
        config.mt5.password = args.password
        config.mt5.path = args.path
        config.backtest.timeframe = args.timeframe
        run_live(config, token=getattr(args, "token", ""),
                 chat_id=getattr(args, "chat_id", ""))


if __name__ == "__main__":
    main()
