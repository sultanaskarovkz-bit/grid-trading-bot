"""
Веб-панель управления торговым ботом.
Запуск: streamlit run dashboard.py
Откроется в браузере по адресу http://localhost:8501
"""

import json
import subprocess
import sys
import os
import time
import signal
from pathlib import Path
from datetime import datetime

import streamlit as st
import pandas as pd
import numpy as np

# Page config
st.set_page_config(
    page_title="Grid Trading Bot",
    page_icon="\U0001f4b9",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Paths ---
BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "best_config.json"
STATE_FILE = BASE_DIR / "signal_state.json"
REPORTS_DIR = BASE_DIR / "reports"
REPORTS_OPT_DIR = BASE_DIR / "reports_optimized"

# --- Helpers ---

def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def load_equity_csv(folder: str = "reports") -> pd.DataFrame | None:
    path = BASE_DIR / folder / "equity_curve.csv"
    if path.exists():
        return pd.read_csv(path, index_col=0, parse_dates=True)
    return None


def load_trade_log(folder: str = "reports") -> pd.DataFrame | None:
    path = BASE_DIR / folder / "trade_log.csv"
    if path.exists():
        return pd.read_csv(path)
    return None


# ============================================================
# SIDEBAR — Navigation
# ============================================================

st.sidebar.title("\U0001f4b9 Grid Trading Bot")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Навигация",
    [
        "\U0001f3e0 Главная",
        "\U00002699\U0000fe0f Настройки сетки",
        "\U0001f4f2 Telegram",
        "\U0001f4ca Бэктест",
        "\U0001f527 Оптимизация",
        "\U0001f4e1 Онлайн-сигналы",
        "\U0001f4c4 MetaTrader 5",
        "\U00002753 Инструкция",
    ],
)

st.sidebar.markdown("---")

# Bot status
state = load_state()
if state.get("virtual_equity"):
    st.sidebar.metric("Баланс", f"${state['virtual_equity']:,.2f}")
    active = sum(1 for v in state.get("active_positions", {}).values() if v)
    st.sidebar.metric("Активных пар", active)


# ============================================================
# PAGE: Home
# ============================================================

if page == "\U0001f3e0 Главная":
    st.title("\U0001f4b9 Мультивалютный сеточный торговый бот")
    st.markdown("### Адаптивная сетка с умным управлением рисками")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Пар", "6", help="EURUSD, GBPUSD, EURCHF, EURJPY, USDCHF, USDJPY")
    col2.metric("Сигналов/нед", "~10", help="EMA, пробои, откаты, импульсы")
    col3.metric("Win Rate", "87.7%", help="По результатам бэктеста")
    col4.metric("Sharpe", "2.76", help="Коэффициент Шарпа")

    st.markdown("---")

    st.markdown("""
    #### Как работает бот

    | Компонент | Описание |
    |-----------|----------|
    | **Сетка ордеров** | Открывает позиции с увеличением лота на каждом уровне |
    | **Таймауты** | Между уровнями: 30мин, 1ч, 2ч, 4ч, 8ч... |
    | **ATR-адаптация** | Расстояние между ордерами подстраивается под волатильность |
    | **Трендовый фильтр** | EMA 90/328 определяет направление входа |
    | **Корреляционный фильтр** | Не открывает одинаковые позиции на похожих парах |
    | **Тейк-профит** | Закрытие по паре при достижении % от баланса |
    | **Трейлинг-стоп** | Защита прибыли при откате |
    | **Стоп-лосс** | Индивидуальный по паре + портфельный аварийный |

    #### Режимы работы

    1. **Онлайн-сигналы** — бот анализирует рынок и шлёт сигналы в Telegram
    2. **Бэктест** — тестирование на исторических данных
    3. **Оптимизация** — автоподбор лучших параметров
    4. **Live-торговля** — автоматическая торговля через MetaTrader 5
    """)

    # Show equity curve if available
    eq = load_equity_csv("reports_optimized") or load_equity_csv("reports")
    if eq is not None:
        st.markdown("---")
        st.markdown("#### Кривая доходности (последний бэктест)")
        st.line_chart(eq["equity"] if "equity" in eq.columns else eq.iloc[:, 0])


# ============================================================
# PAGE: Grid Settings
# ============================================================

elif page == "\U00002699\U0000fe0f Настройки сетки":
    st.title("\U00002699\U0000fe0f Настройки сетки")
    st.markdown("Настройте параметры стратегии. Изменения сохраняются в `best_config.json`.")

    config = load_config()

    with st.form("grid_settings"):
        st.subheader("Параметры сетки")
        col1, col2 = st.columns(2)

        with col1:
            base_dist = st.number_input(
                "Базовое расстояние (пипсы)",
                value=config.get("base_grid_distance_pips", 30.0),
                min_value=5.0, max_value=100.0, step=1.0,
                help="Расстояние между первым и вторым ордером в пипсах"
            )
            dist_mult = st.number_input(
                "Множитель расстояния",
                value=config.get("grid_distance_multiplier", 1.5),
                min_value=1.0, max_value=3.0, step=0.1,
                help="Каждый следующий уровень увеличивает расстояние на этот множитель"
            )
            lot_mult = st.number_input(
                "Множитель лота",
                value=config.get("lot_multiplier", 1.5),
                min_value=1.0, max_value=3.0, step=0.1,
                help="Каждый следующий уровень увеличивает лот на этот множитель"
            )
            max_levels = st.number_input(
                "Макс. уровней сетки",
                value=config.get("max_grid_levels", 7),
                min_value=2, max_value=15, step=1,
                help="Максимальное количество ордеров в сетке по одной паре"
            )

        with col2:
            base_lot = st.number_input(
                "Базовый лот",
                value=config.get("base_lot_size", 0.01),
                min_value=0.01, max_value=1.0, step=0.01,
                help="Размер первого ордера"
            )
            atr_mult = st.number_input(
                "ATR множитель",
                value=config.get("atr_multiplier", 1.5),
                min_value=0.5, max_value=3.0, step=0.1,
                help="Адаптация расстояния к волатильности"
            )
            time_delay = st.number_input(
                "Базовый таймаут (секунды)",
                value=config.get("base_time_delay_seconds", 1800),
                min_value=300, max_value=14400, step=300,
                help="Минимальная задержка перед вторым ордером"
            )
            time_mult = st.number_input(
                "Множитель таймаута",
                value=config.get("time_delay_multiplier", 2.0),
                min_value=1.0, max_value=4.0, step=0.5,
                help="Каждый следующий таймаут умножается на это"
            )

        st.subheader("Управление рисками")
        col3, col4 = st.columns(2)

        with col3:
            tp_pct = st.number_input(
                "Тейк-профит (% от баланса)",
                value=config.get("fix_take_profit_pct", 1.5),
                min_value=0.1, max_value=10.0, step=0.1,
                help="При какой прибыли закрыть корзину по паре"
            )
            stop_dd = st.number_input(
                "Стоп новых ордеров (% просадки)",
                value=config.get("stop_drawdown_pct", 15.0),
                min_value=3.0, max_value=40.0, step=1.0,
                help="При какой просадке перестать открывать новые ордера"
            )
            hard_stop = st.number_input(
                "Аварийный стоп (% просадки)",
                value=config.get("max_portfolio_drawdown_pct", 20.0),
                min_value=5.0, max_value=50.0, step=1.0,
                help="При какой просадке закрыть ВСЁ"
            )

        with col4:
            risk_pct = st.number_input(
                "Риск на сделку (%)",
                value=config.get("risk_per_trade_pct", 1.0),
                min_value=0.1, max_value=5.0, step=0.1,
            )
            corr_thresh = st.number_input(
                "Порог корреляции",
                value=config.get("correlation_threshold", 0.85),
                min_value=0.5, max_value=1.0, step=0.05,
                help="Блокировка пар с корреляцией выше этого значения"
            )

        st.subheader("Фильтры")
        col5, col6 = st.columns(2)

        with col5:
            ema_fast = st.number_input("EMA быстрая", value=config.get("ema_fast", 50),
                                        min_value=10, max_value=200)
            ema_slow = st.number_input("EMA медленная", value=config.get("ema_slow", 200),
                                        min_value=50, max_value=500)

        with col6:
            trend_on = st.checkbox("Трендовый фильтр", value=config.get("trend_filter_enabled", True))
            corr_on = st.checkbox("Корреляционный фильтр", value=config.get("correlation_filter_enabled", True))
            session_on = st.checkbox("Сессионный фильтр", value=config.get("session_filter_enabled", True))
            dynamic_lot = st.checkbox("Динамический лот", value=config.get("dynamic_lot_enabled", True))

        submitted = st.form_submit_button("\U0001f4be Сохранить настройки", use_container_width=True)

        if submitted:
            new_config = {
                "base_grid_distance_pips": base_dist,
                "grid_distance_multiplier": dist_mult,
                "base_lot_size": base_lot,
                "lot_multiplier": lot_mult,
                "max_grid_levels": max_levels,
                "base_time_delay_seconds": time_delay,
                "time_delay_multiplier": time_mult,
                "atr_period": 14,
                "atr_multiplier": atr_mult,
                "fix_take_profit_pct": tp_pct,
                "stop_drawdown_pct": stop_dd,
                "max_portfolio_drawdown_pct": hard_stop,
                "trend_filter_enabled": trend_on,
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
                "correlation_filter_enabled": corr_on,
                "correlation_window": 100,
                "correlation_threshold": corr_thresh,
                "max_correlated_positions": 2,
                "session_filter_enabled": session_on,
                "session_start_utc": 7,
                "session_end_utc": 21,
                "dynamic_lot_enabled": dynamic_lot,
                "risk_per_trade_pct": risk_pct,
                "equity_base": 10000.0,
            }
            save_config(new_config)
            st.success("\U00002705 Настройки сохранены!")

    # Preview grid levels
    st.markdown("---")
    st.subheader("Предпросмотр уровней сетки")
    config = load_config()
    preview_data = []
    for level in range(config.get("max_grid_levels", 7)):
        delay_s = 0 if level == 0 else int(
            config.get("base_time_delay_seconds", 1800)
            * (config.get("time_delay_multiplier", 2.0) ** (level - 1))
        )
        if delay_s == 0:
            delay_text = "Сразу"
        elif delay_s < 3600:
            delay_text = f"{delay_s // 60} мин"
        else:
            delay_text = f"{delay_s / 3600:.1f} ч"

        dist = 0 if level == 0 else config.get("base_grid_distance_pips", 30) * (
            config.get("grid_distance_multiplier", 1.5) ** (level - 1)
        )
        lot = config.get("base_lot_size", 0.01) * (
            config.get("lot_multiplier", 1.5) ** level
        )
        preview_data.append({
            "Уровень": level,
            "Задержка": delay_text,
            "Расстояние (пипсы)": f"{dist:.1f}",
            "Лот": f"{lot:.4f}",
        })
    st.table(pd.DataFrame(preview_data))


# ============================================================
# PAGE: Telegram
# ============================================================

elif page == "\U0001f4f2 Telegram":
    st.title("\U0001f4f2 Настройка Telegram")

    st.markdown("""
    ### Как подключить Telegram

    **Шаг 1.** Откройте [@BotFather](https://t.me/BotFather) в Telegram

    **Шаг 2.** Отправьте `/newbot`, придумайте имя и username

    **Шаг 3.** Скопируйте полученный **TOKEN** (длинная строка типа `123456:ABC-DEF...`)

    **Шаг 4.** Откройте [@userinfobot](https://t.me/userinfobot) и скопируйте ваш **Chat ID** (число)

    **Шаг 5.** Вставьте данные ниже и нажмите "Проверить"
    """)

    token = st.text_input("Bot Token", type="password", placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
    chat_id = st.text_input("Chat ID", placeholder="987654321")

    if st.button("Проверить подключение", use_container_width=True):
        if token and chat_id:
            from telegram_bot import TelegramNotifier
            tg = TelegramNotifier(token=token, chat_id=chat_id)
            success = tg.send_message(
                "\U00002705 <b>Бот подключён!</b>\n\nТорговые сигналы будут приходить сюда."
            )
            if success:
                st.success("\U00002705 Сообщение отправлено! Проверьте Telegram.")
                # Save to .env file
                env_path = BASE_DIR / ".env"
                with open(env_path, "w") as f:
                    f.write(f"TELEGRAM_BOT_TOKEN={token}\n")
                    f.write(f"TELEGRAM_CHAT_ID={chat_id}\n")
                st.info("Данные сохранены в .env файл")
            else:
                st.error("\U0000274c Ошибка отправки. Проверьте Token и Chat ID.")
        else:
            st.warning("Введите Token и Chat ID")

    st.markdown("---")
    st.markdown("""
    ### Что присылает бот

    | Уведомление | Пример |
    |-------------|--------|
    | \U0001f7e2 Сигнал на вход | `LONG EURUSD @ 1.08500` |
    | \U0000274c Закрытие в минус | `EURUSD закрыт: -$150.00 (Стоп-лосс)` |
    | \U00002705 Закрытие в плюс | `USDJPY закрыт: +$320.00 (Тейк-профит)` |
    | \U0001f4ca Статус портфеля | Баланс, просадка, P&L за день |
    | \U0001f50d Обзор рынка | Тренды и сигналы по всем парам |
    """)


# ============================================================
# PAGE: Backtest
# ============================================================

elif page == "\U0001f4ca Бэктест":
    st.title("\U0001f4ca Бэктест")
    st.markdown("Тестирование стратегии на исторических данных")

    col1, col2, col3 = st.columns(3)
    with col1:
        start_date = st.date_input("Начало", value=pd.Timestamp("2024-06-01"))
    with col2:
        end_date = st.date_input("Конец", value=pd.Timestamp("2026-04-01"))
    with col3:
        equity = st.number_input("Начальный депозит ($)", value=10000, step=1000)

    if st.button("\U000025b6\U0000fe0f Запустить бэктест", use_container_width=True):
        with st.spinner("Загрузка данных и запуск бэктеста..."):
            result = subprocess.run(
                [sys.executable, "main.py", "backtest",
                 "--start", str(start_date), "--end", str(end_date),
                 "--equity", str(equity), "--no-show"],
                capture_output=True, text=True, cwd=str(BASE_DIR),
                timeout=300,
            )

        if result.returncode == 0:
            st.success("\U00002705 Бэктест завершён!")

            # Parse results from output
            lines = result.stdout + result.stderr
            for line in lines.split("\n"):
                if "Total Return" in line:
                    st.markdown(f"**{line.strip()}**")
                elif any(k in line for k in ["Max Drawdown", "Sharpe", "Profit Factor",
                                              "Win Rate", "Total Basket", "Calmar"]):
                    st.text(line.strip())

            # Show charts
            eq = load_equity_csv("reports")
            if eq is not None:
                st.markdown("### Кривая доходности")
                st.line_chart(eq["equity"] if "equity" in eq.columns else eq.iloc[:, 0])

            trades = load_trade_log("reports")
            if trades is not None:
                st.markdown("### Лог сделок")
                st.dataframe(trades, use_container_width=True)
        else:
            st.error(f"Ошибка: {result.stderr[-500:]}")


# ============================================================
# PAGE: Optimization
# ============================================================

elif page == "\U0001f527 Оптимизация":
    st.title("\U0001f527 Оптимизация параметров")
    st.markdown("Автоматический подбор лучших параметров с помощью ИИ (Optuna)")

    col1, col2 = st.columns(2)
    with col1:
        n_trials = st.slider("Количество попыток", 20, 500, 100, step=10,
                              help="Больше = точнее, но дольше. 100 попыток ~ 7 мин")
    with col2:
        metric = st.selectbox("Метрика оптимизации", [
            ("sharpe_ratio", "Sharpe Ratio (баланс доходности и риска)"),
            ("calmar_ratio", "Calmar Ratio (доходность / просадка)"),
            ("profit_factor", "Profit Factor (прибыль / убыток)"),
        ], format_func=lambda x: x[1])

    if st.button("\U0001f680 Запустить оптимизацию", use_container_width=True):
        with st.spinner(f"Оптимизация: {n_trials} попыток (это может занять несколько минут)..."):
            result = subprocess.run(
                [sys.executable, "main.py", "optimize",
                 "--trials", str(n_trials), "--metric", metric[0]],
                capture_output=True, text=True, cwd=str(BASE_DIR),
                timeout=600,
            )

        if result.returncode == 0:
            st.success("\U00002705 Оптимизация завершена! Параметры сохранены.")

            output = result.stdout + result.stderr
            # Find results section
            for line in output.split("\n"):
                if any(k in line for k in ["Best ", "Total Return", "Max Drawdown",
                                            "Sharpe", "Profit Factor", "Win Rate",
                                            "Calmar", "base_grid", "lot_mult",
                                            "fix_take", "stop_draw", "ema_"]):
                    st.text(line.strip())

            st.info("Новые параметры сохранены в best_config.json и автоматически применятся.")
        else:
            st.error(f"Ошибка: {result.stderr[-500:]}")


# ============================================================
# PAGE: Live Signals
# ============================================================

elif page == "\U0001f4e1 Онлайн-сигналы":
    st.title("\U0001f4e1 Онлайн-сигналы")
    st.markdown("Бот анализирует рынок в реальном времени и шлёт сигналы в Telegram")

    # Check if .env exists
    env_path = BASE_DIR / ".env"
    token = ""
    chat_id = ""
    if env_path.exists():
        for line in open(env_path):
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                token = line.split("=", 1)[1].strip()
            elif line.startswith("TELEGRAM_CHAT_ID="):
                chat_id = line.split("=", 1)[1].strip()

    if not token:
        st.warning("\U000026a0\U0000fe0f Telegram не настроен. Перейдите в раздел 'Telegram' для настройки.")
    else:
        st.success(f"\U00002705 Telegram подключён (Chat ID: {chat_id})")

    st.markdown("---")

    col1, col2 = st.columns(2)
    with col1:
        virtual_equity = st.number_input("Виртуальный баланс ($)", value=10000, step=1000)

    st.markdown("### Запуск")
    st.code(
        f'python main.py signals --token "{token or "ВАШ_ТОКЕН"}" --chat-id "{chat_id or "ВАШ_CHAT_ID"}"',
        language="bash",
    )

    if st.button("\U000025b6\U0000fe0f Запустить бота (в фоне)", use_container_width=True):
        cmd = [sys.executable, "main.py", "signals"]
        if token:
            cmd.extend(["--token", token, "--chat-id", chat_id])
        cmd.extend(["--equity", str(virtual_equity)])

        pid_file = BASE_DIR / "bot.pid"

        # Check if already running
        if pid_file.exists():
            old_pid = int(open(pid_file).read().strip())
            st.warning(f"Бот уже запущен (PID: {old_pid}). Остановите его перед перезапуском.")
        else:
            proc = subprocess.Popen(
                cmd, cwd=str(BASE_DIR),
                stdout=open(BASE_DIR / "bot.log", "a"),
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            with open(pid_file, "w") as f:
                f.write(str(proc.pid))
            st.success(f"\U00002705 Бот запущен в фоне! PID: {proc.pid}")
            st.info("Сигналы будут приходить в Telegram. Лог: bot.log")

    if st.button("\U000023f9\U0000fe0f Остановить бота", use_container_width=True):
        pid_file = BASE_DIR / "bot.pid"
        if pid_file.exists():
            pid = int(open(pid_file).read().strip())
            try:
                os.kill(pid, signal.SIGTERM)
                pid_file.unlink()
                st.success(f"\U00002705 Бот остановлен (PID: {pid})")
            except OSError:
                pid_file.unlink()
                st.info("Бот уже был остановлен")
        else:
            st.info("Бот не запущен")

    # Show state
    state = load_state()
    if state:
        st.markdown("---")
        st.markdown("### Текущее состояние")
        col1, col2 = st.columns(2)
        col1.metric("Виртуальный баланс", f"${state.get('virtual_equity', 0):,.2f}")
        active = state.get("active_positions", {})
        col2.metric("Активных позиций", sum(1 for v in active.values() if v and v.get("orders")))

        if active:
            for sym, pos in active.items():
                if pos and pos.get("orders"):
                    direction = pos.get("direction", "?")
                    levels = len(pos.get("orders", []))
                    st.text(f"  {sym}: {direction.upper()} | {levels} уровней")

    # Show log
    log_file = BASE_DIR / "bot.log"
    if log_file.exists():
        st.markdown("---")
        st.markdown("### Последние записи лога")
        with open(log_file) as f:
            lines = f.readlines()
        st.code("".join(lines[-20:]), language="text")


# ============================================================
# PAGE: MetaTrader 5
# ============================================================

elif page == "\U0001f4c4 MetaTrader 5":
    st.title("\U0001f4c4 Подключение к MetaTrader 5")

    st.markdown("""
    ### Что нужно для Live-торговли

    1. **MetaTrader 5** — скачайте с сайта вашего брокера и установите
    2. **Демо или реальный счёт** — данные для входа от брокера
    3. **Python-пакет MetaTrader5** — установится автоматически

    ### Пошаговая инструкция

    **Шаг 1.** Установите MetaTrader 5 и войдите в свой счёт

    **Шаг 2.** Разрешите алготрейдинг:
    - Сервис -> Настройки -> Советники
    - Включите "Разрешить алгоритмическую торговлю"

    **Шаг 3.** Установите Python-пакет:
    ```
    pip install MetaTrader5
    ```

    **Шаг 4.** Запустите бота:
    """)

    col1, col2 = st.columns(2)
    with col1:
        server = st.text_input("Сервер брокера", placeholder="MetaQuotes-Demo")
        login = st.text_input("Логин (номер счёта)", placeholder="12345678")
    with col2:
        password = st.text_input("Пароль", type="password")
        mt5_path = st.text_input("Путь к MT5 (необязательно)",
                                  placeholder=r"C:\Program Files\MetaTrader 5\terminal64.exe")

    if server and login and password:
        cmd = f'python main.py live --server "{server}" --login {login} --password "{password}"'
        if mt5_path:
            cmd += f' --path "{mt5_path}"'
        st.code(cmd, language="bash")

    st.markdown("""
    ---
    ### Важно

    - **Сначала протестируйте на демо-счёте!**
    - Бот торгует рыночными ордерами (Market Execution)
    - Убедитесь что все 6 пар доступны у вашего брокера
    - MetaTrader 5 должен быть открыт во время работы бота
    """)


# ============================================================
# PAGE: Instructions
# ============================================================

elif page == "\U00002753 Инструкция":
    st.title("\U00002753 Инструкция по работе")

    st.markdown("""
    ## Быстрый старт

    ### 1. Настройте Telegram
    Перейдите в раздел **Telegram**, подключите бота

    ### 2. Запустите онлайн-сигналы
    Перейдите в раздел **Онлайн-сигналы**, нажмите "Запустить"

    ### 3. Получайте сигналы
    Бот будет присылать уведомления о входах и выходах

    ---

    ## Как менять настройки сетки

    1. Перейдите в раздел **Настройки сетки**
    2. Измените нужные параметры
    3. Нажмите **Сохранить**
    4. Перезапустите бота (если он запущен)

    ---

    ## Что означают параметры

    | Параметр | Что делает | Больше = |
    |----------|------------|----------|
    | Базовое расстояние | Пипсы до 2-го ордера | Реже усредняет |
    | Множитель расстояния | Ширина следующих уровней | Более широкая сетка |
    | Множитель лота | Рост объёма по уровням | Агрессивнее |
    | Тейк-профит | % прибыли для закрытия | Реже фиксирует |
    | Стоп-лосс | % просадки для стопа | Терпит больший убыток |
    | ATR множитель | Адаптация к волатильности | Шире на волатильном рынке |

    ---

    ## Как запустить без интерфейса (из консоли)

    ```bash
    # Бэктест
    python main.py backtest --start 2024-01-01 --end 2025-12-31

    # Оптимизация
    python main.py optimize --trials 200

    # Онлайн-сигналы
    python main.py signals --token "TOKEN" --chat-id "CHAT_ID"

    # Live торговля через MT5
    python main.py live --server broker.com --login 12345 --password pass
    ```

    ---

    ## FAQ

    **Бот работает по реальным данным?**
    Да. В режиме "Онлайн-сигналы" данные загружаются с Yahoo Finance в реальном времени.
    В режиме "Live" данные берутся напрямую из MetaTrader 5.

    **Нужен ли VPS?**
    Для постоянной работы — да. Бот должен быть запущен 24/5.
    Для периодического анализа — нет, можно запускать на своём ПК.

    **Безопасно ли это?**
    Бот НЕ хранит пароли на сервере. Все данные локальны.
    Результаты бэктеста не гарантируют будущую прибыль.
    Всегда начинайте с демо-счёта.
    """)
