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
MT5_CONFIG_FILE = BASE_DIR / "mt5_config.json"

# --- Broker Database ---
BROKERS = {
    "Exness": {
        "servers": [
            "Exness-MT5Trial",
            "Exness-MT5Trial2",
            "Exness-MT5Trial3",
            "Exness-MT5Trial4",
            "Exness-MT5Trial5",
            "Exness-MT5Trial6",
            "Exness-MT5Trial7",
            "Exness-MT5Trial8",
            "Exness-MT5Trial9",
            "Exness-MT5Trial10",
            "Exness-MT5Trial11",
            "Exness-MT5Trial12",
            "Exness-MT5Trial13",
            "Exness-MT5Trial14",
            "Exness-MT5Trial15",
            "Exness-MT5Trial16",
            "Exness-MT5Real",
            "Exness-MT5Real2",
            "Exness-MT5Real3",
            "Exness-MT5Real4",
            "Exness-MT5Real5",
            "Exness-MT5Real6",
            "Exness-MT5Real7",
            "Exness-MT5Real8",
            "Exness-MT5Real9",
            "Exness-MT5Real10",
            "Exness-MT5Real11",
            "Exness-MT5Real12",
            "Exness-MT5Real13",
            "Exness-MT5Real14",
            "Exness-MT5Real15",
        ],
        "symbol_suffix": "m",
        "description": "Международный брокер, от 0.0 пипс спред",
    },
    "RoboForex": {
        "servers": [
            "RoboForex-MetaTrader5",
            "RoboForex-Demo",
            "RoboForex-ECN",
            "RoboForex-Prime",
        ],
        "symbol_suffix": "",
        "description": "CySEC лицензия, бонусы на депозит",
    },
    "XM": {
        "servers": [
            "XMGlobal-MT5",
            "XMGlobal-MT5 2",
            "XMGlobal-MT5 3",
            "XMGlobal-MT5 4",
        ],
        "symbol_suffix": "",
        "description": "Популярный брокер, демо без ограничений",
    },
    "FBS": {
        "servers": [
            "FBS-Demo",
            "FBS-Real",
            "FBS-Real-2",
            "FBS-Real-3",
        ],
        "symbol_suffix": "",
        "description": "Низкий порог входа, cent-счета",
    },
    "Alpari": {
        "servers": [
            "Alpari-MT5-Demo",
            "Alpari-MT5",
            "Alpari-MT5-2",
        ],
        "symbol_suffix": "",
        "description": "Один из старейших брокеров СНГ",
    },
    "InstaForex": {
        "servers": [
            "InstaForex-1MT5.com",
            "InstaForex-2MT5.com",
        ],
        "symbol_suffix": "",
        "description": "Фиксированные спреды, центовые счета",
    },
    "MetaQuotes (Demo)": {
        "servers": [
            "MetaQuotes-Demo",
        ],
        "symbol_suffix": "",
        "description": "Встроенный демо-сервер MetaTrader",
    },
    "Другой брокер": {
        "servers": [],
        "symbol_suffix": "",
        "description": "Ввести сервер вручную",
    },
}


# --- Helpers ---

def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def load_mt5_config() -> dict:
    if MT5_CONFIG_FILE.exists():
        with open(MT5_CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_mt5_config(config: dict):
    with open(MT5_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


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


def ensure_mt5_package():
    """Install MetaTrader5 package if not present."""
    try:
        import MetaTrader5
        return True
    except ImportError:
        with st.spinner("Устанавливаю пакет MetaTrader5..."):
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "MetaTrader5", "--quiet"],
                capture_output=True, text=True, timeout=120,
            )
            return result.returncode == 0


def mt5_connect(server, login, password):
    """Connect to MT5 and return (success, info_or_error)."""
    import MetaTrader5 as mt5
    if not mt5.initialize():
        return False, f"MT5 не запущен. Откройте MetaTrader 5 и попробуйте снова.\nОшибка: {mt5.last_error()}"
    authorized = mt5.login(login=int(login), password=password, server=server)
    if not authorized:
        mt5.shutdown()
        return False, f"Не удалось войти. Проверьте логин, пароль и сервер.\nОшибка: {mt5.last_error()}"
    info = mt5.account_info()
    return True, info


def mt5_open_trades_now(server, login, password):
    """Analyze market and open trades immediately."""
    import MetaTrader5 as mt5
    from config import AppConfig, MT5Config, GridConfig
    from mt5_connector import MT5Connector, LiveTrader

    grid_cfg = GridConfig()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            best = json.load(f)
        for k, v in best.items():
            if hasattr(grid_cfg, k):
                setattr(grid_cfg, k, v)

    mt5_cfg = MT5Config(server=server, login=int(login), password=password)
    config = AppConfig(grid=grid_cfg, mt5=mt5_cfg)
    connector = MT5Connector(mt5_cfg)

    if not connector.connect():
        return False, "Не удалось подключиться к MT5", []

    trader = LiveTrader(config, connector)
    symbols = [p.symbol for p in config.get_enabled_pairs()]

    try:
        trader._tick(symbols, "1h")
        positions = connector.get_open_positions()
        account = connector.get_account_info()
        connector.disconnect()
        return True, account, positions
    except Exception as e:
        connector.disconnect()
        return False, str(e), []


# ============================================================
# CUSTOM CSS
# ============================================================

st.markdown("""
<style>
    .block-container { padding-top: 2rem; }
    .stMetric { background: #f8f9fa; padding: 15px; border-radius: 10px; }
    div[data-testid="stMetricValue"] { font-size: 1.8rem; }
    .param-help {
        background: #f0f2f6; padding: 12px; border-radius: 8px;
        margin-bottom: 10px; font-size: 0.9em; border-left: 3px solid #4CAF50;
    }
    .warning-box {
        background: #fff3cd; padding: 12px; border-radius: 8px;
        border-left: 3px solid #ffc107; margin: 10px 0;
    }
    .success-box {
        background: #d4edda; padding: 12px; border-radius: 8px;
        border-left: 3px solid #28a745; margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.title("\U0001f4b9 Grid Trading Bot")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Меню",
    [
        "\U0001f3e0 Главная",
        "\U0001f4c4 Подключение к бирже",
        "\U0001f4b0 Торговля",
        "\U00002699\U0000fe0f Настройки сетки",
        "\U0001f4f2 Telegram",
        "\U0001f4ca Бэктест",
        "\U0001f527 Оптимизация",
        "\U00002753 Инструкция",
    ],
)

st.sidebar.markdown("---")

# Connection status in sidebar
mt5_cfg = load_mt5_config()
if mt5_cfg.get("server"):
    st.sidebar.success(f"Биржа: {mt5_cfg.get('broker', '?')}")
    st.sidebar.caption(f"Счёт: {mt5_cfg.get('login', '?')}")
else:
    st.sidebar.warning("Биржа не подключена")

# Bot state in sidebar
state = load_state()
if state.get("virtual_equity"):
    st.sidebar.metric("Баланс", f"${state['virtual_equity']:,.2f}")


# ============================================================
# PAGE: Home
# ============================================================

if page == "\U0001f3e0 Главная":
    st.title("\U0001f4b9 Grid Trading Bot")
    st.markdown("#### Автоматическая торговля на валютном рынке")

    st.markdown("---")

    # Quick status
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Валютных пар", "6")
    col2.metric("Сигналов/неделю", "7-12")
    col3.metric("Win Rate", "87.7%")
    col4.metric("Доходность теста", "+239%")

    st.markdown("---")

    st.markdown("""
    ### Как начать за 3 шага

    **Шаг 1.** Подключите биржу
    > Перейдите в раздел **"Подключение к бирже"** в меню слева.
    > Выберите брокера, введите логин/пароль - готово.

    **Шаг 2.** Нажмите "Открыть сделки"
    > В разделе **"Торговля"** нажмите одну кнопку - бот проанализирует рынок
    > и сам откроет позиции на вашем счёте.

    **Шаг 3.** Следите за результатом
    > Сделки видны прямо в MetaTrader 5.
    > Подключите **Telegram** чтобы получать уведомления на телефон.
    """)

    st.markdown("---")

    st.markdown("""
    ### Что умеет бот

    | Функция | Описание |
    |---------|----------|
    | **Автоторговля** | Сам открывает и закрывает сделки в MetaTrader 5 |
    | **Сигналы в Telegram** | Присылает рекомендации покупать/продавать |
    | **Бэктест** | Тест стратегии на прошлых данных - увидите сколько бы заработали |
    | **Оптимизация** | Автоподбор лучших настроек одной кнопкой |
    | **Умная сетка** | Сам подстраивается под волатильность рынка |
    """)

    # Show equity curve if available
    eq = load_equity_csv("reports_optimized")
    if eq is None:
        eq = load_equity_csv("reports")
    if eq is not None:
        st.markdown("---")
        st.markdown("#### Результат последнего бэктеста")
        st.line_chart(eq["equity"] if "equity" in eq.columns else eq.iloc[:, 0])


# ============================================================
# PAGE: Connect to Broker
# ============================================================

elif page == "\U0001f4c4 Подключение к бирже":
    st.title("\U0001f4c4 Подключение к бирже")
    st.markdown("Подключите бота к MetaTrader 5 для автоматической торговли")

    st.markdown("---")

    # Step 1 - Prerequisites
    st.markdown("""
    ### Перед подключением

    1. **Скачайте MetaTrader 5** с сайта вашего брокера и установите
    2. **Откройте MetaTrader 5** и войдите в свой счёт (демо или реальный)
    3. **Включите автоторговлю**: вверху нажмите кнопку "Algo Trading" (должна стать зелёной)
    """)

    st.markdown("---")

    # Step 2 - Broker selection
    st.markdown("### Выберите брокера и введите данные")

    broker_name = st.selectbox(
        "Брокер",
        list(BROKERS.keys()),
        help="Выберите вашего брокера из списка. Если его нет - выберите 'Другой брокер'",
    )

    broker_info = BROKERS[broker_name]
    if broker_info["description"]:
        st.caption(broker_info["description"])

    # Server selection
    if broker_name == "Другой брокер":
        server = st.text_input(
            "Сервер (введите вручную)",
            placeholder="BrokerName-MT5",
            help="Сервер виден в MetaTrader: Файл -> Войти в торговый счёт",
        )
    else:
        servers = broker_info["servers"]
        server = st.selectbox(
            "Сервер",
            servers,
            help="Выберите сервер. Если не знаете какой - посмотрите в MetaTrader внизу окна",
        )

    col1, col2 = st.columns(2)
    with col1:
        login = st.text_input("Логин (номер счёта)", placeholder="12345678")
    with col2:
        password = st.text_input("Пароль", type="password")

    st.markdown("")

    # Connect button
    if st.button("\U0001f50c Подключиться", use_container_width=True, type="primary"):
        if not server or not login or not password:
            st.error("Заполните все поля: сервер, логин и пароль")
        else:
            if not ensure_mt5_package():
                st.error("Не удалось установить пакет MetaTrader5. Попробуйте: pip install MetaTrader5")
            else:
                with st.spinner("Подключаюсь к MetaTrader 5..."):
                    success, result = mt5_connect(server, login, password)

                if success:
                    info = result
                    import MetaTrader5 as mt5
                    account_type = "Демо" if info.trade_mode == 0 else "Реальный"
                    mt5.shutdown()

                    # Save connection
                    save_mt5_config({
                        "broker": broker_name,
                        "server": server,
                        "login": login,
                        "password": password,
                    })

                    st.success("\U00002705 Подключено!")
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Баланс", f"${info.balance:,.2f}")
                    col2.metric("Плечо", f"1:{info.leverage}")
                    col3.metric("Валюта", info.currency)
                    col4.metric("Тип счёта", account_type)

                    st.info("Теперь перейдите в раздел **Торговля** чтобы начать.")
                else:
                    st.error(result)

    # Show current connection
    mt5_cfg = load_mt5_config()
    if mt5_cfg.get("server"):
        st.markdown("---")
        st.markdown("### Текущее подключение")
        st.markdown(f"""
        - **Брокер:** {mt5_cfg.get('broker', '?')}
        - **Сервер:** {mt5_cfg.get('server', '?')}
        - **Счёт:** {mt5_cfg.get('login', '?')}
        """)
        if st.button("\U0000274c Отключиться"):
            MT5_CONFIG_FILE.unlink(missing_ok=True)
            st.rerun()


# ============================================================
# PAGE: Trading
# ============================================================

elif page == "\U0001f4b0 Торговля":
    st.title("\U0001f4b0 Торговля")

    mt5_cfg = load_mt5_config()

    if not mt5_cfg.get("server"):
        st.warning("\U000026a0\U0000fe0f Биржа не подключена. Перейдите в **Подключение к бирже**.")
    else:
        st.success(f"Подключено: **{mt5_cfg.get('broker')}** | Счёт: **{mt5_cfg.get('login')}**")
        st.markdown("---")

        # --- Quick Trade ---
        st.markdown("### \U000026a1 Быстрая торговля")
        st.markdown("""
        Нажмите кнопку - бот проанализирует рынок прямо сейчас и откроет сделки.
        Не надо ждать идеальный момент - бот сам определит направление по каждой паре.
        """)

        if st.button("\U0001f680 Проанализировать рынок и открыть сделки", use_container_width=True, type="primary"):
            if not ensure_mt5_package():
                st.error("Пакет MetaTrader5 не установлен")
            else:
                with st.spinner("Анализирую 6 валютных пар..."):
                    success, account_or_error, positions = mt5_open_trades_now(
                        mt5_cfg["server"], mt5_cfg["login"], mt5_cfg["password"]
                    )

                if success:
                    account = account_or_error

                    col1, col2, col3 = st.columns(3)
                    col1.metric("Баланс", f"${account['balance']:,.2f}")
                    col2.metric("Эквити", f"${account['equity']:,.2f}")
                    col3.metric("Открыто позиций", len(positions))

                    if positions:
                        st.markdown("#### Открытые позиции")
                        pos_data = []
                        for p in positions:
                            direction = "\U0001f7e2 LONG" if p["type"] == "long" else "\U0001f534 SHORT"
                            pnl_color = "+" if p["profit"] >= 0 else ""
                            pos_data.append({
                                "Пара": p["symbol"],
                                "Направление": direction,
                                "Объём": f"{p['volume']} лот",
                                "Цена входа": p["price_open"],
                                "Текущая цена": p["price_current"],
                                "P&L": f"${pnl_color}{p['profit']:.2f}",
                            })
                        st.table(pd.DataFrame(pos_data))
                        st.success("Сделки открыты! Смотрите их в MetaTrader 5 во вкладке 'Торговля'")
                    else:
                        st.info("Бот проанализировал рынок, но подходящих точек входа сейчас нет. Попробуйте позже.")
                else:
                    st.error(f"Ошибка: {account_or_error}")

        st.markdown("---")

        # --- Status ---
        st.markdown("### \U0001f4ca Текущие позиции")
        if st.button("\U0001f504 Обновить", use_container_width=True):
            if ensure_mt5_package():
                with st.spinner("Загружаю..."):
                    success, result = mt5_connect(mt5_cfg["server"], mt5_cfg["login"], mt5_cfg["password"])
                    if success:
                        import MetaTrader5 as mt5
                        info = result
                        col1, col2, col3 = st.columns(3)
                        col1.metric("Баланс", f"${info.balance:,.2f}")
                        col2.metric("Эквити", f"${info.equity:,.2f}")
                        col3.metric("Прибыль", f"${info.profit:,.2f}")

                        positions = mt5.positions_get()
                        if positions:
                            pos_data = []
                            for p in positions:
                                direction = "\U0001f7e2 LONG" if p.type == 0 else "\U0001f534 SHORT"
                                pnl = f"+${p.profit:.2f}" if p.profit >= 0 else f"-${abs(p.profit):.2f}"
                                pos_data.append({
                                    "Пара": p.symbol,
                                    "Направление": direction,
                                    "Объём": f"{p.volume} лот",
                                    "Цена входа": p.price_open,
                                    "Текущая": p.price_current,
                                    "P&L": pnl,
                                })
                            st.table(pd.DataFrame(pos_data))
                        else:
                            st.info("Нет открытых позиций")
                        mt5.shutdown()
                    else:
                        st.error(result)

        st.markdown("---")

        # --- Close All ---
        st.markdown("### \U000023f9 Закрыть все позиции")
        st.markdown("Закроет ВСЕ открытые сделки на счёте")
        if st.button("\U0000274c Закрыть всё", use_container_width=True):
            if ensure_mt5_package():
                with st.spinner("Закрываю позиции..."):
                    try:
                        from config import MT5Config
                        from mt5_connector import MT5Connector
                        mt5_config = MT5Config(
                            server=mt5_cfg["server"],
                            login=int(mt5_cfg["login"]),
                            password=mt5_cfg["password"],
                        )
                        connector = MT5Connector(mt5_config)
                        if connector.connect():
                            closed = connector.close_all()
                            connector.disconnect()
                            st.success(f"\U00002705 Закрыто позиций: {closed}")
                        else:
                            st.error("Не удалось подключиться к MT5")
                    except Exception as e:
                        st.error(f"Ошибка: {e}")

        st.markdown("---")

        # --- Auto Trading ---
        st.markdown("### \U0001f916 Автоматический режим")
        st.markdown("""
        Бот будет **постоянно** анализировать рынок и торговать сам.
        Работает пока компьютер включён и MetaTrader 5 открыт.
        """)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("\U000025b6\U0000fe0f Запустить автоторговлю", use_container_width=True):
                pid_file = BASE_DIR / "bot_live.pid"
                if pid_file.exists():
                    st.warning("Автоторговля уже запущена")
                else:
                    cmd = [
                        sys.executable, "main.py", "live",
                        "--server", mt5_cfg["server"],
                        "--login", str(mt5_cfg["login"]),
                        "--password", mt5_cfg["password"],
                    ]
                    proc = subprocess.Popen(
                        cmd, cwd=str(BASE_DIR),
                        stdout=open(BASE_DIR / "bot.log", "a"),
                        stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    )
                    with open(pid_file, "w") as f:
                        f.write(str(proc.pid))
                    st.success(f"\U00002705 Автоторговля запущена!")

        with col2:
            if st.button("\U000023f9\U0000fe0f Остановить автоторговлю", use_container_width=True):
                pid_file = BASE_DIR / "bot_live.pid"
                if pid_file.exists():
                    pid = int(open(pid_file).read().strip())
                    try:
                        os.kill(pid, signal.SIGTERM)
                        st.success("Автоторговля остановлена")
                    except OSError:
                        pass
                    pid_file.unlink()
                else:
                    st.info("Автоторговля не запущена")


# ============================================================
# PAGE: Grid Settings
# ============================================================

elif page == "\U00002699\U0000fe0f Настройки сетки":
    st.title("\U00002699\U0000fe0f Настройки сетки")

    st.markdown("""
    Сеточная стратегия - это система усреднения позиций.
    Если цена пошла против вас, бот открывает дополнительные ордера с увеличенным объёмом,
    чтобы средняя цена входа сдвинулась ближе к текущей.
    Когда цена возвращается - вся корзина закрывается в плюс.
    """)

    st.markdown("---")

    config = load_config()

    with st.form("grid_settings"):

        # === GRID STRUCTURE ===
        st.markdown("### \U0001f4cf Структура сетки")
        st.markdown('<div class="param-help">'
                     '<b>Это основа стратегии.</b> '
                     'Определяет когда и как бот добавляет ордера если цена идёт против позиции.'
                     '</div>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)

        with col1:
            base_dist = st.slider(
                "\U0001f4cf Расстояние между ордерами (пипсы)",
                min_value=10.0, max_value=100.0, step=1.0,
                value=float(config.get("base_grid_distance_pips", 30.0)),
                help="Через сколько пипсов открыть следующий ордер",
            )
            st.caption("Больше = безопаснее, меньше сделок. Меньше = чаще торгует, выше риск.")

            lot_mult = st.slider(
                "\U0001f4c8 Множитель объёма",
                min_value=1.0, max_value=3.0, step=0.1,
                value=float(config.get("lot_multiplier", 1.5)),
                help="Во сколько раз увеличивать объём на каждом уровне",
            )
            st.caption("1.0 = одинаковый объём. 1.5 = каждый следующий в 1.5 раза больше. 2.0+ = агрессивно.")

            max_levels = st.slider(
                "\U0001f4ca Максимум уровней",
                min_value=2, max_value=15, step=1,
                value=int(config.get("max_grid_levels", 7)),
                help="Сколько максимум ордеров может быть в одной корзине",
            )
            st.caption("Больше уровней = терпит больше просадки. Меньше = быстрее режет убытки.")

        with col2:
            base_lot = st.slider(
                "\U0001f4b5 Начальный лот",
                min_value=0.01, max_value=1.0, step=0.01,
                value=float(config.get("base_lot_size", 0.01)),
                help="Размер первого ордера в лотах",
            )
            st.caption("0.01 = минимальный. Для $10,000 депозита обычно 0.01-0.05.")

            dist_mult = st.slider(
                "\U0001f50d Расширение сетки",
                min_value=1.0, max_value=3.0, step=0.1,
                value=float(config.get("grid_distance_multiplier", 1.5)),
                help="Каждый следующий ордер ставится дальше предыдущего",
            )
            st.caption("1.0 = равномерно. 1.5 = каждый уровень на 50% дальше. Снижает риск на глубоких уровнях.")

            atr_mult = st.slider(
                "\U0001f321\U0000fe0f Адаптация к волатильности (ATR)",
                min_value=0.5, max_value=3.0, step=0.1,
                value=float(config.get("atr_multiplier", 1.5)),
                help="Автоматически расширяет сетку когда рынок волатильный",
            )
            st.caption("Выше = шире расстояние на волатильном рынке. Защищает от быстрых движений.")

        st.markdown("---")

        # === TIMING ===
        st.markdown("### \U000023f0 Таймауты между ордерами")
        st.markdown('<div class="param-help">'
                     '<b>Защита от слишком быстрого набора позиций.</b> '
                     'Бот ждёт определённое время перед открытием каждого следующего уровня.'
                     '</div>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            time_delay_min = st.slider(
                "\U000023f0 Базовая задержка (минуты)",
                min_value=5, max_value=240, step=5,
                value=int(config.get("base_time_delay_seconds", 1800)) // 60,
                help="Минимальное время ожидания перед вторым ордером",
            )
            st.caption(f"Текущее: {time_delay_min} мин. Рекомендуется 30-60 минут.")

        with col2:
            time_mult = st.slider(
                "\U000023f1\U0000fe0f Множитель задержки",
                min_value=1.0, max_value=4.0, step=0.5,
                value=float(config.get("time_delay_multiplier", 2.0)),
                help="Каждый следующий уровень ждёт в X раз дольше",
            )
            st.caption(f"При {time_delay_min}мин и множителе {time_mult}: "
                       f"1й={time_delay_min}мин, 2й={int(time_delay_min*time_mult)}мин, "
                       f"3й={int(time_delay_min*time_mult**2)}мин")

        st.markdown("---")

        # === RISK MANAGEMENT ===
        st.markdown("### \U0001f6e1\U0000fe0f Управление рисками")
        st.markdown('<div class="param-help">'
                     '<b>Когда фиксировать прибыль и когда резать убытки.</b> '
                     'Это самые важные параметры для сохранения депозита.'
                     '</div>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)

        with col1:
            tp_pct = st.slider(
                "\U00002705 Тейк-профит (% от баланса)",
                min_value=0.5, max_value=10.0, step=0.5,
                value=float(config.get("fix_take_profit_pct", 2.0)),
                help="При какой прибыли закрыть все ордера по паре",
            )
            st.caption("1-2% = часто фиксирует по чуть-чуть. 3-5% = реже но крупнее. Рекомендуется 1.5-3%.")

            stop_dd = st.slider(
                "\U000026a0\U0000fe0f Стоп новых ордеров (% просадки)",
                min_value=5.0, max_value=40.0, step=1.0,
                value=float(config.get("stop_drawdown_pct", 15.0)),
                help="При какой просадке перестать открывать новые ордера",
            )
            st.caption("Бот перестаёт усредняться когда просадка слишком большая.")

        with col2:
            hard_stop = st.slider(
                "\U0001f6d1 Аварийный стоп (% просадки)",
                min_value=10.0, max_value=50.0, step=1.0,
                value=float(config.get("max_portfolio_drawdown_pct", 20.0)),
                help="При какой просадке закрыть ВСЁ и зафиксировать убыток",
            )
            st.caption("Последняя линия защиты. Закроет все позиции если убыток слишком большой.")

            risk_pct = st.slider(
                "\U0001f4b0 Риск на сделку (%)",
                min_value=0.5, max_value=5.0, step=0.5,
                value=float(config.get("risk_per_trade_pct", 1.0)),
                help="Какой процент баланса рискуется на одну сделку",
            )
            st.caption("1% = консервативно. 2-3% = умеренно. 5% = агрессивно.")

        st.markdown("---")

        # === FILTERS ===
        st.markdown("### \U0001f50d Фильтры")
        st.markdown('<div class="param-help">'
                     '<b>Дополнительная защита.</b> '
                     'Фильтры помогают не торговать в плохие моменты и не дублировать позиции.'
                     '</div>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)

        with col1:
            trend_on = st.checkbox("Трендовый фильтр", value=config.get("trend_filter_enabled", True),
                                    help="Торговать только по направлению тренда (EMA)")
            corr_on = st.checkbox("Корреляционный фильтр", value=config.get("correlation_filter_enabled", True),
                                   help="Не открывать одинаковые позиции на похожих парах (EURUSD и GBPUSD)")
            session_on = st.checkbox("Сессионный фильтр", value=config.get("session_filter_enabled", True),
                                      help="Торговать только в активные часы (Лондон + Нью-Йорк)")
            dynamic_lot = st.checkbox("Автоматический лот", value=config.get("dynamic_lot_enabled", True),
                                       help="Подстраивать размер ордера под размер баланса")

        with col2:
            ema_fast = st.number_input("EMA быстрая", value=config.get("ema_fast", 50),
                                        min_value=10, max_value=200,
                                        help="Быстрая скользящая средняя для определения тренда")
            ema_slow = st.number_input("EMA медленная", value=config.get("ema_slow", 200),
                                        min_value=50, max_value=500,
                                        help="Медленная скользящая средняя для определения тренда")
            corr_thresh = st.slider("Порог корреляции", min_value=0.5, max_value=1.0, step=0.05,
                                     value=float(config.get("correlation_threshold", 0.85)),
                                     help="Блокировать пары с корреляцией выше этого значения")

        submitted = st.form_submit_button("\U0001f4be Сохранить настройки", use_container_width=True, type="primary")

        if submitted:
            new_config = {
                "base_grid_distance_pips": base_dist,
                "grid_distance_multiplier": dist_mult,
                "base_lot_size": base_lot,
                "lot_multiplier": lot_mult,
                "max_grid_levels": max_levels,
                "base_time_delay_seconds": time_delay_min * 60,
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
    st.markdown("### Предпросмотр уровней сетки")
    st.markdown("Так будет выглядеть сетка с текущими настройками:")

    config = load_config()
    preview_data = []
    total_lot = 0
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
        total_lot += lot

        preview_data.append({
            "Уровень": f"#{level + 1}",
            "Когда открывается": delay_text,
            "Расстояние от входа": f"{dist:.0f} пипсов" if level > 0 else "Первый вход",
            "Объём": f"{lot:.3f} лот",
            "Сумма объёмов": f"{total_lot:.3f} лот",
        })
    st.table(pd.DataFrame(preview_data))


# ============================================================
# PAGE: Telegram
# ============================================================

elif page == "\U0001f4f2 Telegram":
    st.title("\U0001f4f2 Уведомления в Telegram")

    st.markdown("""
    Бот может присылать вам сигналы и результаты сделок прямо в Telegram.

    ### Как настроить (2 минуты)

    **1.** Откройте Telegram, найдите **@BotFather**, напишите `/newbot`

    **2.** Придумайте имя и username для бота, скопируйте **TOKEN**

    **3.** Найдите **@userinfobot**, нажмите Start, скопируйте ваш **Chat ID** (число)

    **4.** Вставьте данные ниже:
    """)

    token = st.text_input("Bot Token", type="password", placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
    chat_id = st.text_input("Chat ID", placeholder="987654321")

    if st.button("\U0001f4e8 Отправить тестовое сообщение", use_container_width=True, type="primary"):
        if token and chat_id:
            from telegram_bot import TelegramNotifier
            tg = TelegramNotifier(token=token, chat_id=chat_id)
            success = tg.send_message(
                "\U00002705 <b>Бот подключён!</b>\n\nТорговые сигналы будут приходить сюда."
            )
            if success:
                st.success("\U00002705 Готово! Проверьте Telegram - там должно быть сообщение.")
                env_path = BASE_DIR / ".env"
                with open(env_path, "w") as f:
                    f.write(f"TELEGRAM_BOT_TOKEN={token}\n")
                    f.write(f"TELEGRAM_CHAT_ID={chat_id}\n")
            else:
                st.error("Не удалось отправить. Проверьте Token и Chat ID.")
        else:
            st.warning("Введите Token и Chat ID")

    # Check if already configured
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        has_token = False
        for line in open(env_path):
            if line.startswith("TELEGRAM_BOT_TOKEN=") and len(line.strip().split("=", 1)[1]) > 5:
                has_token = True
        if has_token:
            st.markdown("---")
            st.success("\U00002705 Telegram уже настроен")

    st.markdown("---")
    st.markdown("""
    ### Что присылает бот

    | Сообщение | Когда |
    |-----------|-------|
    | **LONG EURUSD @ 1.0850** | Бот видит сигнал на покупку |
    | **SHORT USDJPY @ 158.50** | Бот видит сигнал на продажу |
    | **ЗАКРЫТО: EURUSD +$320** | Сделка закрылась в плюс |
    | **ЗАКРЫТО: GBPUSD -$150** | Сделка закрылась в минус |
    | **Статус портфеля** | Каждые 4 часа: баланс, просадка |
    """)


# ============================================================
# PAGE: Backtest
# ============================================================

elif page == "\U0001f4ca Бэктест":
    st.title("\U0001f4ca Бэктест")
    st.markdown("Прогоните стратегию на исторических данных и посмотрите сколько бы заработали")

    st.markdown("---")

    col1, col2, col3 = st.columns(3)
    with col1:
        start_date = st.date_input("Начало", value=pd.Timestamp("2024-06-01"))
    with col2:
        end_date = st.date_input("Конец", value=pd.Timestamp("2026-04-01"))
    with col3:
        equity = st.number_input("Начальный депозит ($)", value=10000, step=1000)

    if st.button("\U000025b6\U0000fe0f Запустить тест", use_container_width=True, type="primary"):
        with st.spinner("Загружаю данные и тестирую стратегию... (1-2 минуты)"):
            result = subprocess.run(
                [sys.executable, "main.py", "backtest",
                 "--start", str(start_date), "--end", str(end_date),
                 "--equity", str(equity), "--no-show"],
                capture_output=True, text=True, cwd=str(BASE_DIR),
                timeout=300,
            )

        if result.returncode == 0:
            st.success("\U00002705 Тест завершён!")

            lines = result.stdout + result.stderr
            for line in lines.split("\n"):
                if "Total Return" in line:
                    st.markdown(f"**{line.strip()}**")
                elif any(k in line for k in ["Max Drawdown", "Sharpe", "Profit Factor",
                                              "Win Rate", "Total Basket", "Calmar"]):
                    st.text(line.strip())

            eq = load_equity_csv("reports")
            if eq is not None:
                st.markdown("### Рост депозита")
                st.line_chart(eq["equity"] if "equity" in eq.columns else eq.iloc[:, 0])

            trades = load_trade_log("reports")
            if trades is not None:
                st.markdown("### Все сделки")
                st.dataframe(trades, use_container_width=True)
        else:
            st.error(f"Ошибка: {result.stderr[-500:]}")


# ============================================================
# PAGE: Optimization
# ============================================================

elif page == "\U0001f527 Оптимизация":
    st.title("\U0001f527 Оптимизация настроек")
    st.markdown("Бот сам переберёт сотни комбинаций настроек и найдёт лучшую")

    st.markdown("---")

    col1, col2 = st.columns(2)
    with col1:
        n_trials = st.slider("Количество попыток", 20, 500, 100, step=10,
                              help="Больше = точнее результат, но дольше считает")
        st.caption("100 попыток ~ 7 мин, 200 ~ 15 мин, 500 ~ 30 мин")
    with col2:
        metric = st.selectbox("Что оптимизировать", [
            ("sharpe_ratio", "Баланс доходности и риска (Sharpe)"),
            ("calmar_ratio", "Доходность к просадке (Calmar)"),
            ("profit_factor", "Отношение прибыли к убыткам"),
        ], format_func=lambda x: x[1])

    if st.button("\U0001f680 Запустить оптимизацию", use_container_width=True, type="primary"):
        with st.spinner(f"Ищу лучшие настройки ({n_trials} попыток)... Это может занять несколько минут."):
            result = subprocess.run(
                [sys.executable, "main.py", "optimize",
                 "--trials", str(n_trials), "--metric", metric[0]],
                capture_output=True, text=True, cwd=str(BASE_DIR),
                timeout=600,
            )

        if result.returncode == 0:
            st.success("\U00002705 Готово! Лучшие настройки сохранены и будут применены автоматически.")

            output = result.stdout + result.stderr
            for line in output.split("\n"):
                if any(k in line for k in ["Best ", "Total Return", "Max Drawdown",
                                            "Sharpe", "Profit Factor", "Win Rate",
                                            "Calmar", "base_grid", "lot_mult",
                                            "fix_take", "stop_draw", "ema_"]):
                    st.text(line.strip())
        else:
            st.error(f"Ошибка: {result.stderr[-500:]}")


# ============================================================
# PAGE: Instructions
# ============================================================

elif page == "\U00002753 Инструкция":
    st.title("\U00002753 Инструкция")

    st.markdown("""
    ## Что делает бот

    Бот смотрит на 6 валютных пар (EURUSD, GBPUSD, EURCHF, EURJPY, USDCHF, USDJPY)
    и торгует по сеточной стратегии - открывает позиции и усредняет их если цена идёт против.

    ---

    ## Быстрый старт

    1. **Подключите биржу** - выберите брокера, введите логин и пароль
    2. **Откройте сделки** - нажмите одну кнопку в разделе "Торговля"
    3. **Настройте Telegram** - чтобы получать уведомления на телефон

    ---

    ## Что означают настройки сетки

    ### Основные параметры

    **Расстояние между ордерами** - через сколько пипсов бот откроет следующий ордер
    если цена пойдёт против вас. Чем больше - тем безопаснее, но реже торгует.

    **Множитель объёма** - во сколько раз увеличивается объём каждого следующего ордера.
    - 1.0 = все ордера одинаковые (консервативно)
    - 1.3-1.5 = умеренное усиление
    - 2.0+ = агрессивное усиление (больше прибыль, но и больше риск)

    **Максимум уровней** - сколько ордеров максимум может быть в одной корзине.
    Больше уровней = бот может пересидеть большее движение, но рискует большей суммой.

    ### Управление рисками

    **Тейк-профит** - при какой прибыли (% от баланса) закрыть все ордера по паре.
    - 1% = часто фиксирует небольшую прибыль
    - 3-5% = реже, но крупнее

    **Стоп новых ордеров** - при какой просадке бот перестаёт добавлять новые ордера.
    Защита от бесконечного усреднения.

    **Аварийный стоп** - при какой просадке закрыть ВСЁ с убытком.
    Последняя линия защиты депозита.

    ### Фильтры

    **Трендовый фильтр** - бот торгует только в направлении тренда.
    Покупает когда тренд вверх, продаёт когда вниз.

    **Корреляционный фильтр** - не открывает одинаковые позиции на похожих парах.
    Например EURUSD и GBPUSD часто ходят вместе - бот не откроет покупку на обоих сразу.

    **Сессионный фильтр** - торгует только когда биржи активны (Лондон + Нью-Йорк).
    Ночью и в выходные не торгует.

    ---

    ## Режимы работы

    **Быстрая торговля** - нажали кнопку, бот проанализировал рынок и открыл сделки.

    **Автоматический режим** - бот постоянно следит за рынком и сам открывает/закрывает
    сделки. Работает пока компьютер включён.

    **Сигналы в Telegram** - бот присылает рекомендации, а вы сами решаете входить или нет.

    ---

    ## Частые вопросы

    **Обязательно ли подключать MetaTrader?**
    Для автоторговли - да. Для сигналов в Telegram - нет.

    **Данные настоящие?**
    Да, цены загружаются с биржи в реальном времени.

    **Нужен ли VPS?**
    Если хотите чтобы бот работал когда компьютер выключен - да.
    Для периодического анализа - нет.

    **Работает на Mac?**
    Сигналы в Telegram - да. Автоторговля через MetaTrader - только на Windows.
    """)
