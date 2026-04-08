"""
MetaTrader 5 connector for live trading.
Handles connection, order execution, and position management.
"""

import logging
import time
from datetime import datetime

import pandas as pd

from config import MT5Config, Direction, GridConfig, PairConfig, AppConfig
from indicators import compute_indicators, correlation_matrix
from risk_manager import RiskManager
from strategy import GridStrategy, PairState

logger = logging.getLogger(__name__)

# MT5 timeframe mapping
MT5_TIMEFRAMES = {
    "1m": None,   # will be set after import
    "5m": None,
    "15m": None,
    "30m": None,
    "1h": None,
    "4h": None,
    "1d": None,
}


def _init_mt5_timeframes():
    """Initialize MT5 timeframe constants after import."""
    try:
        import MetaTrader5 as mt5
        MT5_TIMEFRAMES.update({
            "1m": mt5.TIMEFRAME_M1,
            "5m": mt5.TIMEFRAME_M5,
            "15m": mt5.TIMEFRAME_M15,
            "30m": mt5.TIMEFRAME_M30,
            "1h": mt5.TIMEFRAME_H1,
            "4h": mt5.TIMEFRAME_H4,
            "1d": mt5.TIMEFRAME_D1,
        })
    except ImportError:
        logger.warning("MetaTrader5 package not installed")


class MT5Connector:
    """Low-level MT5 API wrapper."""

    def __init__(self, config: MT5Config):
        self.config = config
        self._connected = False
        self._symbol_map = {}  # maps base symbol (EURUSD) -> broker symbol (EURUSDm)

    def _detect_symbol(self, base_symbol: str) -> str:
        """Detect actual broker symbol name (some brokers add suffix like 'm')."""
        if base_symbol in self._symbol_map:
            return self._symbol_map[base_symbol]

        # Try exact match first
        info = self.mt5.symbol_info(base_symbol)
        if info is not None:
            self._symbol_map[base_symbol] = base_symbol
            return base_symbol

        # Try common suffixes
        for suffix in ["m", ".m", ".i", ".e", ".pro", ".raw", ".std"]:
            candidate = base_symbol + suffix
            info = self.mt5.symbol_info(candidate)
            if info is not None:
                self._symbol_map[base_symbol] = candidate
                logger.info(f"Symbol mapping: {base_symbol} -> {candidate}")
                return candidate

        # Fallback to original
        self._symbol_map[base_symbol] = base_symbol
        return base_symbol

    def connect(self) -> bool:
        try:
            import MetaTrader5 as mt5
            self.mt5 = mt5
            _init_mt5_timeframes()
        except ImportError:
            logger.error("MetaTrader5 package not installed. Install with: pip install MetaTrader5")
            return False

        kwargs = {"timeout": self.config.timeout}
        if self.config.path:
            kwargs["path"] = self.config.path
        if self.config.login:
            kwargs["login"] = self.config.login
            kwargs["password"] = self.config.password
            kwargs["server"] = self.config.server

        if not self.mt5.initialize(**kwargs):
            logger.error(f"MT5 init failed: {self.mt5.last_error()}")
            return False

        info = self.mt5.account_info()
        if info is None:
            logger.error("Failed to get account info")
            return False

        logger.info(f"Connected to {info.server}, account #{info.login}, "
                     f"balance: {info.balance}, leverage: 1:{info.leverage}")
        self._connected = True
        return True

    def disconnect(self) -> None:
        if self._connected:
            self.mt5.shutdown()
            self._connected = False

    def _ensure_connected(self) -> None:
        """Verify MT5 connection is active."""
        if not self._connected:
            raise ConnectionError("Not connected to MT5. Call connect() first.")

    def get_ohlcv(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        self._ensure_connected()
        tf = MT5_TIMEFRAMES.get(timeframe)
        if tf is None:
            raise ValueError(f"Unknown timeframe: {timeframe}")

        broker_symbol = self._detect_symbol(symbol)
        rates = self.mt5.copy_rates_from_pos(broker_symbol, tf, 0, bars)
        if rates is None or len(rates) == 0:
            raise ValueError(f"No data for {symbol}")

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time")
        df = df.rename(columns={
            "open": "open", "high": "high", "low": "low",
            "close": "close", "tick_volume": "volume",
        })
        return df[["open", "high", "low", "close", "volume"]]

    def get_current_price(self, symbol: str) -> tuple:
        """Returns (bid, ask)."""
        self._ensure_connected()
        broker_symbol = self._detect_symbol(symbol)
        tick = self.mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            raise ValueError(f"No tick data for {symbol}")
        return tick.bid, tick.ask

    def get_account_info(self) -> dict:
        self._ensure_connected()
        info = self.mt5.account_info()
        return {
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "profit": info.profit,
        }

    def open_order(self, symbol: str, direction: Direction,
                   lot_size: float, comment: str = "") -> int | None:
        """Place market order. Returns ticket or None."""
        broker_symbol = self._detect_symbol(symbol)
        symbol_info = self.mt5.symbol_info(broker_symbol)
        if symbol_info is None:
            logger.error(f"Symbol {symbol} ({broker_symbol}) not found")
            return None
        if not symbol_info.visible:
            self.mt5.symbol_select(broker_symbol, True)

        bid, ask = self.get_current_price(symbol)
        order_type = self.mt5.ORDER_TYPE_BUY if direction == Direction.LONG else self.mt5.ORDER_TYPE_SELL
        price = ask if direction == Direction.LONG else bid

        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": broker_symbol,
            "volume": lot_size,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": 123456,
            "comment": comment,
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.mt5.ORDER_FILLING_IOC,
        }

        result = self.mt5.order_send(request)
        if result is None or result.retcode != self.mt5.TRADE_RETCODE_DONE:
            error = result.comment if result else "unknown error"
            logger.error(f"Order failed for {broker_symbol}: {error}")
            return None

        logger.info(f"Order opened: {broker_symbol} {direction.value} {lot_size} lots @ {price}, ticket: {result.order}")
        return result.order

    def close_order(self, ticket: int, symbol: str, direction: Direction,
                    lot_size: float) -> bool:
        """Close a specific position by ticket."""
        broker_symbol = self._detect_symbol(symbol)
        bid, ask = self.get_current_price(symbol)
        close_type = self.mt5.ORDER_TYPE_SELL if direction == Direction.LONG else self.mt5.ORDER_TYPE_BUY
        price = bid if direction == Direction.LONG else ask

        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": broker_symbol,
            "volume": lot_size,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": 123456,
            "comment": "grid_close",
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.mt5.ORDER_FILLING_IOC,
        }

        result = self.mt5.order_send(request)
        if result is None or result.retcode != self.mt5.TRADE_RETCODE_DONE:
            error = result.comment if result else "unknown error"
            logger.error(f"Close failed for ticket {ticket}: {error}")
            return False

        logger.info(f"Position closed: ticket {ticket}")
        return True

    def close_all(self, symbol: str | None = None) -> int:
        """Close all positions, optionally filtered by symbol."""
        broker_symbol = self._detect_symbol(symbol) if symbol else None
        positions = self.mt5.positions_get(symbol=broker_symbol) if broker_symbol else self.mt5.positions_get()
        if positions is None:
            return 0

        closed = 0
        for pos in positions:
            direction = Direction.LONG if pos.type == 0 else Direction.SHORT
            if self.close_order(pos.ticket, pos.symbol, direction, pos.volume):
                closed += 1
        return closed

    def get_open_positions(self) -> list:
        """Get all open positions as list of dicts."""
        positions = self.mt5.positions_get()
        if positions is None:
            return []
        return [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "long" if p.type == 0 else "short",
                "volume": p.volume,
                "price_open": p.price_open,
                "price_current": p.price_current,
                "profit": p.profit,
                "time": datetime.fromtimestamp(p.time),
                "comment": p.comment,
            }
            for p in positions
        ]


class LiveTrader:
    """Orchestrates the live trading loop using GridStrategy + MT5Connector."""

    def __init__(self, config: AppConfig, connector: MT5Connector):
        self.config = config
        self.connector = connector
        self.pairs = config.get_enabled_pairs()
        self.risk_manager = RiskManager(config.grid, self.pairs)
        self.strategy = GridStrategy(
            config.grid, self.risk_manager, self.pairs,
            commission_per_lot=config.backtest.commission_per_lot,
        )
        self._running = False

    def run(self, timeframe: str = "1h") -> None:
        """Main live trading loop."""
        if not self.connector.connect():
            logger.error("Failed to connect to MT5")
            return

        self._running = True
        symbols = [p.symbol for p in self.pairs]
        logger.info(f"Live trading started. Pairs: {symbols}, TF: {timeframe}")

        try:
            while self._running:
                self._tick(symbols, timeframe)
                # Wait for next bar
                self._wait_for_next_bar(timeframe)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.connector.disconnect()

    def _tick(self, symbols: list[str], timeframe: str) -> None:
        """Execute one iteration of the trading loop."""
        account = self.connector.get_account_info()
        equity = account["equity"]

        # Load recent data for indicators
        prices = {}
        close_dict = {}
        for symbol in symbols:
            try:
                df = self.connector.get_ohlcv(symbol, timeframe, 300)
                df = compute_indicators(
                    df,
                    atr_period=self.config.grid.atr_period,
                    ema_fast=self.config.grid.ema_fast,
                    ema_slow=self.config.grid.ema_slow,
                )
                last = df.iloc[-1]
                prices[symbol] = {
                    "open": last["open"],
                    "high": last["high"],
                    "low": last["low"],
                    "close": last["close"],
                    "atr": last["atr"],
                    "trend": last["trend"],
                }
                close_dict[symbol] = df["close"]
            except Exception as e:
                logger.error(f"Data error for {symbol}: {e}")

        # Correlation matrix
        corr_matrix = None
        if len(close_dict) > 1:
            corr_matrix = correlation_matrix(
                close_dict, self.config.grid.correlation_window
            )

        from datetime import timezone, timedelta
        tz_offset = self.config.grid.timezone_offset_utc if hasattr(self.config.grid, 'timezone_offset_utc') else 3
        tz_info = timezone(timedelta(hours=tz_offset))
        timestamp = pd.Timestamp.now(tz=tz_info)
        actions = self.strategy.on_bar(timestamp, prices, equity, corr_matrix)

        # Execute actions
        for action in actions:
            self._execute_action(action)

        # Log status
        state = self.strategy.get_portfolio_state()
        logger.info(
            f"Tick @ {timestamp}: equity={equity:.2f}, "
            f"active_pairs={state['active_pairs']}, "
            f"unrealized={state['total_unrealized_pnl']:.2f}"
        )

    def _execute_action(self, action: dict) -> None:
        """Execute a strategy action via MT5."""
        if action["action"] == "open":
            direction = Direction.LONG if action["direction"] == "long" else Direction.SHORT
            ticket = self.connector.open_order(
                action["symbol"], direction, action["lot_size"],
                comment=f"grid_L{action['level']}",
            )
            if ticket:
                # Update strategy state with real ticket
                for state in self.strategy.pair_states.values():
                    for order in state.active_orders:
                        if order.order_id == action["order_id"]:
                            order.order_id = str(ticket)

        elif action["action"] == "close_basket":
            self.connector.close_all(action["symbol"])

    def _wait_for_next_bar(self, timeframe: str) -> None:
        """Sleep until the next bar opens."""
        intervals = {
            "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "4h": 14400, "1d": 86400,
        }
        interval = intervals.get(timeframe, 3600)

        now = time.time()
        next_bar = (int(now / interval) + 1) * interval
        sleep_time = max(1, next_bar - now)
        logger.debug(f"Sleeping {sleep_time:.0f}s until next {timeframe} bar")
        time.sleep(sleep_time)

    def stop(self) -> None:
        self._running = False
