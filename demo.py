"""
=============================================================
  MULTI-CURRENCY ADAPTIVE GRID TRADING BOT — DEMO
=============================================================

  Запуск:  python demo.py

  Скрипт автоматически:
  1. Загрузит исторические данные по 6 валютным парам
  2. Запустит бэктест с оптимизированными параметрами
  3. Покажет результаты, графики и статистику
  4. Сохранит полный отчёт в папку demo_report/
=============================================================
"""

import json
import sys
import os
import time
import logging
from pathlib import Path
from copy import deepcopy

# Force UTF-8 output on Windows
if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def print_header():
    print()
    print("=" * 64)
    print("   MULTI-CURRENCY ADAPTIVE GRID TRADING BOT")
    print("   Мультивалютный адаптивный сеточный торговый робот")
    print("=" * 64)
    print()
    print("  Рынок:       Forex (валютный рынок)")
    print("  Стратегия:   Адаптивная сетка с таймаутами")
    print("  Пары:        EURUSD, GBPUSD, EURCHF, EURJPY, USDCHF, USDJPY")
    print("  Таймфрейм:   1 час (H1)")
    print()
    print("-" * 64)


def print_features():
    print()
    print("  КЛЮЧЕВЫЕ ОСОБЕННОСТИ АЛГОРИТМА:")
    print()
    print("  1. Адаптивный шаг сетки      — ATR подстраивает расстояние")
    print("     между ордерами под текущую волатильность")
    print()
    print("  2. Таймауты между ордерами   -- 30мин > 1ч > 2ч > 4ч")
    print("     Предотвращает лавинное открытие позиций")
    print()
    print("  3. Трендовый фильтр (EMA)    — определяет направление")
    print("     первого ордера по тренду (EMA 90/328)")
    print()
    print("  4. Корреляционный фильтр     — блокирует одинаковые")
    print("     позиции на коррелированных парах (>0.72)")
    print()
    print("  5. Сессионный фильтр         — торговля только в")
    print("     активные сессии (London 07:00 — NY Close 21:00 UTC)")
    print()
    print("  6. Per-pair basket TP/SL     — каждая пара закрывается")
    print("     независимо, с trailing stop для защиты прибыли")
    print()
    print("  7. Адаптивный cooldown       — после стопов бот ждёт")
    print("     дольше перед повторным входом (4ч → 8ч → 16ч...)")
    print()
    print("  8. Динамический лот          — размер позиции")
    print("     масштабируется от текущего equity")
    print()
    print("-" * 64)


def print_params(grid_config):
    print()
    print("  ОПТИМИЗИРОВАННЫЕ ПАРАМЕТРЫ:")
    print()
    print(f"  Grid Distance Base:     {grid_config.base_grid_distance_pips:.1f} pips")
    print(f"  Grid Distance Mult:     x{grid_config.grid_distance_multiplier:.2f}")
    print(f"  Lot Multiplier:         x{grid_config.lot_multiplier:.2f}")
    print(f"  Max Grid Levels:        {grid_config.max_grid_levels}")
    print(f"  ATR Multiplier:         {grid_config.atr_multiplier:.2f}")
    print(f"  Take Profit (basket):   {grid_config.fix_take_profit_pct:.2f}% equity")
    print(f"  Stop Drawdown:          {grid_config.stop_drawdown_pct:.1f}%")
    print(f"  Hard Stop (portfolio):  {grid_config.max_portfolio_drawdown_pct:.1f}%")
    print(f"  EMA Fast/Slow:          {grid_config.ema_fast}/{grid_config.ema_slow}")
    print(f"  Correlation Threshold:  {grid_config.correlation_threshold:.2f}")
    print(f"  Time Delay Base:        {grid_config.base_time_delay_seconds}s ({grid_config.base_time_delay_seconds//60} min)")
    print(f"  Risk Per Trade:         {grid_config.risk_per_trade_pct:.2f}%")
    print()
    print("-" * 64)


def print_time_delays(grid_config):
    print()
    print("  ТАЙМАУТЫ МЕЖДУ УРОВНЯМИ СЕТКИ:")
    print()
    for level in range(min(grid_config.max_grid_levels, 8)):
        delay = grid_config.get_time_delay(level)
        if delay == 0:
            delay_str = "сразу"
        elif delay < 3600:
            delay_str = f"{delay // 60} мин"
        else:
            hours = delay / 3600
            delay_str = f"{hours:.1f} ч"

        dist = grid_config.get_grid_distance_pips(level)
        lot = grid_config.get_lot_size(level, 10000)

        print(f"  Уровень {level}: задержка {delay_str:>8s}  |  "
              f"расстояние {dist:>6.1f} pips  |  лот {lot:.3f}")
    print()
    print("-" * 64)


def load_best_config():
    """Load optimized parameters from best_config.json."""
    from config import AppConfig, GridConfig

    config = AppConfig()
    config_path = Path("best_config.json")

    if config_path.exists():
        with open(config_path) as f:
            params = json.load(f)
        for key, value in params.items():
            if hasattr(config.grid, key):
                setattr(config.grid, key, value)
        print("  [OK] Загружены оптимизированные параметры из best_config.json")
    else:
        print("  [!]  best_config.json не найден — используются параметры по умолчанию")
        print("       Запустите: python main.py optimize --trials 100")

    return config


def run_demo():
    print_header()
    input("  Нажмите Enter для начала демонстрации...")

    print_features()
    input("  Нажмите Enter для загрузки параметров...")

    # Load config
    config = load_best_config()
    print_params(config.grid)
    print_time_delays(config.grid)
    input("  Нажмите Enter для загрузки данных...")

    # Load data
    from data_manager import DataManager
    from backtester import BacktestEngine
    from reporting import Reporter

    dm = DataManager()
    symbols = [p.symbol for p in config.get_enabled_pairs()]

    print()
    print("  ЗАГРУЗКА ДАННЫХ:")
    print()

    data = dm.load_all_pairs(symbols, "1h", "2024-06-01", "2026-04-01")
    data = dm.align_data(data)

    if not data:
        print("  [ОШИБКА] Не удалось загрузить данные.")
        print("  Проверьте интернет-соединение и повторите попытку.")
        return

    print()
    for sym, df in data.items():
        print(f"  {sym}: {len(df):>6} баров  "
              f"({df.index[0].strftime('%Y-%m-%d')} — {df.index[-1].strftime('%Y-%m-%d')})")

    print()
    print("-" * 64)
    input("  Нажмите Enter для запуска бэктеста...")

    # Run backtest
    print()
    print("  ЗАПУСК БЭКТЕСТА...")
    print(f"  Начальный депозит: $10,000")
    print(f"  Период: {list(data.values())[0].index[0].strftime('%Y-%m-%d')} — "
          f"{list(data.values())[0].index[-1].strftime('%Y-%m-%d')}")
    print()

    start_time = time.time()
    engine = BacktestEngine(config)
    result = engine.run(data)
    elapsed = time.time() - start_time

    print(f"  Бэктест завершён за {elapsed:.1f} сек.")
    print()
    print("-" * 64)

    # Results
    print()
    print(result.summary())

    # Additional analysis
    print()
    print("  ДОПОЛНИТЕЛЬНАЯ АНАЛИТИКА:")
    print()

    final_equity = result.equity_curve.iloc[-1] if not result.equity_curve.empty else 10000
    print(f"  Начальный капитал:     $10,000.00")
    print(f"  Конечный капитал:      ${final_equity:>12,.2f}")
    print(f"  Чистая прибыль:        ${final_equity - 10000:>12,.2f}")
    print()

    if result.total_trades > 0:
        wins = [t.pnl for t in engine.run.__code__.co_consts if False]  # placeholder
        basket_closes = [a for a in result.trade_log if a.get("action") == "close_basket"]

        tp_trades = [a for a in basket_closes if a.get("reason") == "TAKE_PROFIT"]
        trail_trades = [a for a in basket_closes if a.get("reason") == "TRAILING_TP"]
        sl_trades = [a for a in basket_closes if a.get("reason") in ("PAIR_STOP", "HARD_STOP")]

        print(f"  Take Profit закрытий:  {len(tp_trades)}")
        print(f"  Trailing TP закрытий:  {len(trail_trades)}")
        print(f"  Stop Loss закрытий:    {len(sl_trades)}")
        print()

        if tp_trades:
            avg_tp = sum(a["pnl"] for a in tp_trades) / len(tp_trades)
            print(f"  Средний TP profit:     ${avg_tp:>10,.2f}")
        if sl_trades:
            avg_sl = sum(a["pnl"] for a in sl_trades) / len(sl_trades)
            print(f"  Средний SL loss:       ${avg_sl:>10,.2f}")

        # Per-pair breakdown
        print()
        print("  P&L ПО ПАРАМ:")
        print()
        pair_pnl = {}
        for a in basket_closes:
            sym = a["symbol"]
            pair_pnl[sym] = pair_pnl.get(sym, 0) + a["pnl"]

        for sym in sorted(pair_pnl, key=lambda s: -pair_pnl[s]):
            pnl = pair_pnl[sym]
            bar = "+" * max(1, int(abs(pnl) / max(abs(v) for v in pair_pnl.values()) * 20))
            sign = "+" if pnl >= 0 else "-"
            color_indicator = "[WIN]" if pnl >= 0 else "[LOSS]"
            print(f"  {sym:<8s} {color_indicator} ${pnl:>10,.2f}  {bar}")

    print()
    print("-" * 64)

    # Generate report
    print()
    print("  ГЕНЕРАЦИЯ ОТЧЁТА...")

    reporter = Reporter(result, output_dir="demo_report")
    reporter.generate_full_report(show=True)

    print()
    print("=" * 64)
    print("  ДЕМОНСТРАЦИЯ ЗАВЕРШЕНА")
    print("=" * 64)
    print()
    print("  Файлы отчёта сохранены в папке: demo_report/")
    print()
    print("  Содержимое:")
    print("  - equity_curve.png      — кривая доходности + просадка")
    print("  - monthly_returns.png   — помесячная доходность (heatmap)")
    print("  - trade_distribution.png — распределение P&L по сделкам")
    print("  - pair_contribution.png — вклад каждой пары в P&L")
    print("  - equity_curve.csv      — данные equity для Excel")
    print("  - trade_log.csv         — лог всех сделок")
    print()
    print("  Команды для дальнейшей работы:")
    print()
    print("  python main.py backtest                    — бэктест")
    print("  python main.py optimize --trials 200       — оптимизация")
    print("  python main.py live --server X --login Y   — live торговля")
    print()
    print("=" * 64)


if __name__ == "__main__":
    try:
        run_demo()
    except KeyboardInterrupt:
        print("\n\n  Демонстрация прервана пользователем.")
    except Exception as e:
        print(f"\n  Ошибка: {e}")
        import traceback
        traceback.print_exc()
