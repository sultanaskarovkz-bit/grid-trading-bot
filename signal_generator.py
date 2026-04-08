"""
Real-time signal generator.
Monitors live forex market data, runs strategy analysis,
and sends trade signals via Telegram.

Runs 24/5 as a background service. Two modes:
  - "signals" : analysis only, sends recommendations (no auto-trading)
  - "live"    : analysis + auto-execution via MT5

Data sources:
  - yfinance  : free, ~15min delay (good for signals mode)
  - MT5       : real-time (required for live mode)
"""

import json
import logging
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from config import AppConfig, GridConfig, Direction
from indicators import compute_indicators, correlation_matrix, atr, ema
from risk_manager import RiskManager
from strategy import GridStrategy
from telegram_bot import TelegramNotifier

logger = logging.getLogger(__name__)

# How often to check the market (seconds)
CHECK_INTERVAL_SECONDS = 300  # 5 minutes
# How often to send portfolio status (seconds)
STATUS_INTERVAL_SECONDS = 4 * 3600  # every 4 hours
# How often to send market analysis (seconds)
ANALYSIS_INTERVAL_SECONDS = 8 * 3600  # every 8 hours
# Minimum bars needed for indicators
MIN_BARS = 400


class MarketScanner:
    """
    Additional signal scanner — generates trend/momentum alerts
    independently from the grid strategy. Ensures minimum 5 signals/week.

    Signal types:
    1. EMA Crossover     — when fast EMA crosses slow EMA (new trend)
    2. Range Breakout    — when price breaks 20-bar high/low after consolidation
    3. Trend Continuation — pullback to EMA in a trending market
    4. Reversal Warning  — strong move against trend (potential grid opportunity)
    """

    def __init__(self, config: GridConfig, pairs: list):
        self.config = config
        self.pairs = pairs
        self._last_signals: dict[str, dict] = {}  # track to avoid duplicates
        self._signal_cooldown_hours = 48  # min hours between signals for same pair

    def scan(self, prepared_data: dict[str, pd.DataFrame],
             timestamp: pd.Timestamp) -> list[dict]:
        """Scan all pairs for additional signals. Returns list of signal dicts."""
        signals = []

        for pair_cfg in self.pairs:
            symbol = pair_cfg.symbol
            if symbol not in prepared_data:
                continue

            df = prepared_data[symbol]
            if len(df) < 50:
                continue

            # Check cooldown
            last = self._last_signals.get(symbol)
            if last:
                hours_since = (timestamp - last["time"]).total_seconds() / 3600
                if hours_since < self._signal_cooldown_hours:
                    continue

            signal = self._analyze_pair(df, symbol, pair_cfg, timestamp)
            if signal:
                signals.append(signal)
                self._last_signals[symbol] = {"time": timestamp, "type": signal["type"]}

        return signals

    def _analyze_pair(self, df: pd.DataFrame, symbol: str,
                      pair_cfg, timestamp: pd.Timestamp) -> dict | None:
        """Analyze a single pair for signals."""
        close = df["close"]
        ema_fast = df["ema_fast"]
        ema_slow = df["ema_slow"]
        atr_val = df["atr"]
        trend = df["trend"]

        last_close = float(close.iloc[-1])
        prev_close = float(close.iloc[-2])
        last_atr = float(atr_val.iloc[-1]) if not pd.isna(atr_val.iloc[-1]) else 0
        last_trend = int(trend.iloc[-1]) if not pd.isna(trend.iloc[-1]) else 0
        prev_trend = int(trend.iloc[-2]) if not pd.isna(trend.iloc[-2]) else 0

        if last_atr <= 0:
            return None

        atr_pips = last_atr / pair_cfg.pip_value

        # 1. EMA Crossover — strongest signal
        if last_trend != 0 and prev_trend != 0 and last_trend != prev_trend:
            direction = "LONG" if last_trend > 0 else "SHORT"
            return {
                "type": "EMA_CROSSOVER",
                "symbol": symbol,
                "direction": direction,
                "price": last_close,
                "atr_pips": atr_pips,
                "strength": "STRONG",
                "description": f"EMA {self.config.ema_fast}/{self.config.ema_slow} crossover -> {direction}",
            }

        # 2. Range Breakout — price breaks 20-bar high/low
        if len(close) >= 25:
            high_20 = float(close.iloc[-25:-1].max())
            low_20 = float(close.iloc[-25:-1].min())
            range_size = high_20 - low_20

            # Breakout if range was tight (< 2x ATR) and price breaks out
            if range_size < last_atr * 1.8:
                if last_close > high_20 and last_trend > 0:
                    return {
                        "type": "BREAKOUT",
                        "symbol": symbol,
                        "direction": "LONG",
                        "price": last_close,
                        "atr_pips": atr_pips,
                        "strength": "MEDIUM",
                        "description": f"Breakout above {high_20:.5f} (20-bar high)",
                    }
                elif last_close < low_20 and last_trend < 0:
                    return {
                        "type": "BREAKOUT",
                        "symbol": symbol,
                        "direction": "SHORT",
                        "price": last_close,
                        "atr_pips": atr_pips,
                        "strength": "MEDIUM",
                        "description": f"Breakout below {low_20:.5f} (20-bar low)",
                    }

        # 3. Trend Continuation — pullback to EMA in trending market
        if last_trend != 0:
            last_ema_fast = float(ema_fast.iloc[-1])
            prev_ema_dist = abs(prev_close - float(ema_fast.iloc[-2]))
            curr_ema_dist = abs(last_close - last_ema_fast)

            # Price was far from EMA, now touching it = pullback (strict)
            if prev_ema_dist > last_atr * 0.8 and curr_ema_dist < last_atr * 0.15:
                direction = "LONG" if last_trend > 0 else "SHORT"
                return {
                    "type": "TREND_PULLBACK",
                    "symbol": symbol,
                    "direction": direction,
                    "price": last_close,
                    "atr_pips": atr_pips,
                    "strength": "MEDIUM",
                    "description": f"Pullback to EMA{self.config.ema_fast} in {direction} trend",
                }

        # 4. Strong momentum — big move (> 1.5 ATR in one bar)
        bar_range = abs(last_close - prev_close)
        if bar_range > last_atr * 2.0:
            direction = "LONG" if last_close > prev_close else "SHORT"
            if (direction == "LONG" and last_trend >= 0) or (direction == "SHORT" and last_trend <= 0):
                return {
                    "type": "MOMENTUM",
                    "symbol": symbol,
                    "direction": direction,
                    "price": last_close,
                    "atr_pips": atr_pips,
                    "strength": "MEDIUM",
                    "description": f"Strong {direction} momentum ({bar_range/last_atr:.1f}x ATR move)",
                }

        return None


class LiveDataFeed:
    """Fetches live/recent forex data from yfinance."""

    def __init__(self):
        import yfinance as yf
        self._yf = yf
        self._ticker_map = {
            "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X",
            "EURCHF": "EURCHF=X", "EURJPY": "EURJPY=X",
            "USDCHF": "USDCHF=X", "USDJPY": "USDJPY=X",
            "AUDUSD": "AUDUSD=X", "NZDUSD": "NZDUSD=X",
            "USDCAD": "USDCAD=X",
        }

    def get_recent_data(self, symbol: str, bars: int = MIN_BARS,
                        timeframe: str = "1h") -> pd.DataFrame | None:
        """Get most recent OHLCV data."""
        ticker = self._ticker_map.get(symbol, f"{symbol}=X")
        try:
            # yfinance allows 730 days of 1h data
            days_needed = max(30, bars // 24 + 5)
            raw = self._yf.download(
                ticker,
                period=f"{days_needed}d",
                interval=timeframe,
                progress=False,
                auto_adjust=True,
            )
            if raw.empty:
                return None

            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)

            df = pd.DataFrame({
                "open": raw["Open"].values,
                "high": raw["High"].values,
                "low": raw["Low"].values,
                "close": raw["Close"].values,
            }, index=raw.index)
            df.index.name = "datetime"
            df = df.dropna().tail(bars)
            return df
        except Exception as e:
            logger.error(f"Failed to fetch {symbol}: {e}")
            return None

    def get_all_pairs(self, symbols: list[str],
                      timeframe: str = "1h") -> dict[str, pd.DataFrame]:
        """Get data for all pairs."""
        data = {}
        for symbol in symbols:
            df = self.get_recent_data(symbol, MIN_BARS, timeframe)
            if df is not None and len(df) > 50:
                data[symbol] = df
        return data


class SignalGenerator:
    """
    Main real-time signal engine.
    Monitors market, detects grid entry/exit signals, sends to Telegram.
    """

    def __init__(self, config: AppConfig, telegram: TelegramNotifier):
        self.config = config
        self.telegram = telegram
        self.feed = LiveDataFeed()
        self.pairs = config.get_enabled_pairs()
        self.symbols = [p.symbol for p in self.pairs]

        # Initialize strategy components
        self.risk_manager = RiskManager(config.grid, self.pairs)
        self.strategy = GridStrategy(
            config.grid, self.risk_manager, self.pairs,
            commission_per_lot=config.backtest.commission_per_lot,
        )
        self.scanner = MarketScanner(config.grid, self.pairs)

        # Virtual equity tracking (for signal mode without real account)
        self.virtual_equity = config.backtest.initial_equity
        self._daily_start_equity = self.virtual_equity
        self._last_status_time = 0.0
        self._last_analysis_time = 0.0
        self._running = False

        # State persistence
        self._state_file = Path("signal_state.json")

    def run(self) -> None:
        """Main loop — runs until interrupted."""
        self._running = True
        logger.info(f"Signal generator started. Pairs: {self.symbols}")
        self.telegram.bot_started(self.symbols, "SIGNALS")

        self._load_state()

        try:
            while self._running:
                try:
                    self._tick()
                except Exception as e:
                    logger.error(f"Tick error: {e}")
                    logger.error(traceback.format_exc())
                    self.telegram.error_alert(f"Tick error: {e}")

                # Wait before next check
                self._smart_sleep()

        except KeyboardInterrupt:
            logger.info("Signal generator stopped by user")
        finally:
            self._save_state()
            self.telegram.bot_stopped("shutdown")
            self._running = False

    def _tick(self) -> None:
        """One analysis cycle."""
        now = time.time()

        # 1. Fetch live data
        logger.info("Fetching market data...")
        data = self.feed.get_all_pairs(self.symbols)

        if not data:
            logger.warning("No data available")
            return

        # 2. Compute indicators
        prepared = {}
        for pair in self.pairs:
            if pair.symbol not in data:
                continue
            df = compute_indicators(
                data[pair.symbol],
                atr_period=self.config.grid.atr_period,
                ema_fast=self.config.grid.ema_fast,
                ema_slow=self.config.grid.ema_slow,
            )
            prepared[pair.symbol] = df

        if not prepared:
            return

        # 3. Build current prices dict
        prices = {}
        for symbol, df in prepared.items():
            last = df.iloc[-1]
            prices[symbol] = {
                "open": float(last["open"]),
                "high": float(last["high"]),
                "low": float(last["low"]),
                "close": float(last["close"]),
                "atr": float(last["atr"]) if not pd.isna(last["atr"]) else 0,
                "trend": int(last["trend"]) if not pd.isna(last["trend"]) else 0,
            }

        # 4. Compute correlation matrix
        close_dict = {s: df["close"] for s, df in prepared.items()}
        corr_matrix = None
        if len(close_dict) > 1:
            corr_matrix = correlation_matrix(
                close_dict, self.config.grid.correlation_window
            )

        # 5. Run strategy logic
        tz_offset = self.config.grid.timezone_offset_utc
        tz_info = timezone(timedelta(hours=tz_offset))
        timestamp = pd.Timestamp.now(tz=tz_info)
        actions = self.strategy.on_bar(
            timestamp, prices, self.virtual_equity, corr_matrix
        )

        # 6. Process grid actions — send signals
        for action in actions:
            self._process_action(action, prices)

        # 6b. Run market scanner for additional signals
        scanner_signals = self.scanner.scan(prepared, timestamp)
        for sig in scanner_signals:
            self._send_scanner_signal(sig)

        # 7. Periodic status updates
        if now - self._last_status_time > STATUS_INTERVAL_SECONDS:
            self._send_status(prices)
            self._last_status_time = now

        # 8. Periodic market analysis
        if now - self._last_analysis_time > ANALYSIS_INTERVAL_SECONDS:
            self._send_analysis(prices, prepared)
            self._last_analysis_time = now

        self._save_state()

    def _process_action(self, action: dict, prices: dict) -> None:
        """Send Telegram signal for each action."""
        if action["action"] == "open":
            symbol = action["symbol"]
            direction = action["direction"]
            price = action["price"]
            level = action["level"]
            lot_size = action["lot_size"]

            atr_pips = 0
            trend_text = "NEUTRAL"
            if symbol in prices:
                p = prices[symbol]
                pair_cfg = next((pp for pp in self.pairs if pp.symbol == symbol), None)
                if pair_cfg and p["atr"] > 0:
                    atr_pips = p["atr"] / pair_cfg.pip_value
                trend_text = "UP" if p["trend"] > 0 else ("DOWN" if p["trend"] < 0 else "NEUTRAL")

            reason = ""
            if level == 0:
                reason = "New grid entry (trend signal)"
            else:
                reason = f"Grid level {level} (averaging in)"

            self.telegram.signal_open(
                symbol, direction, price, level, lot_size,
                atr_pips, trend_text, reason
            )
            logger.info(f"SIGNAL: {direction.upper()} {symbol} L{level} @ {price:.5f}")

            # Update virtual equity (commission)
            self.virtual_equity -= action.get("commission", 0)

        elif action["action"] == "close_basket":
            symbol = action["symbol"]
            pnl = action["pnl"]
            reason = action["reason"]
            num_orders = action["num_orders"]

            # Estimate holding time from strategy
            holding_hours = 0
            for trade in self.strategy.trade_history:
                if trade.symbols and trade.symbols[0] == symbol:
                    holding_hours = trade.holding_time_hours

            self.telegram.signal_close(
                symbol, reason, pnl, num_orders, holding_hours
            )
            logger.info(f"SIGNAL CLOSE: {symbol} ({reason}) PnL: {pnl:.2f}")

            self.virtual_equity += pnl

    def _send_scanner_signal(self, signal: dict) -> None:
        """Send a scanner signal to Telegram."""
        direction = signal["direction"]
        symbol = signal["symbol"]
        sig_type = signal["type"]
        price = signal["price"]
        atr_pips = signal["atr_pips"]
        strength = signal["strength"]
        description = signal["description"]

        self.telegram.signal_open(
            symbol=symbol,
            direction=direction.lower(),
            price=price,
            level=0,
            lot_size=0,  # recommendation only
            atr_pips=atr_pips,
            trend=direction,
            reason=f"[{sig_type}] {description} (strength: {strength})",
        )
        logger.info(f"SCANNER SIGNAL: {sig_type} {direction} {symbol} @ {price:.5f}")

    def _send_status(self, prices: dict) -> None:
        """Send portfolio status to Telegram."""
        state = self.strategy.get_portfolio_state()
        dd = self.risk_manager.current_drawdown_pct(
            self.virtual_equity + state["total_unrealized_pnl"]
        )
        daily_pnl = (self.virtual_equity + state["total_unrealized_pnl"]) - self._daily_start_equity

        self.telegram.portfolio_update(
            equity=self.virtual_equity,
            unrealized_pnl=state["total_unrealized_pnl"],
            active_pairs=state["active_pairs"],
            drawdown_pct=dd,
            daily_pnl=daily_pnl,
        )

        # Reset daily P&L tracker at midnight (local timezone)
        tz_offset = self.config.grid.timezone_offset_utc
        now = datetime.now(timezone(timedelta(hours=tz_offset)))
        if now.hour == 0 and now.minute < 10:
            self._daily_start_equity = self.virtual_equity

    def _send_analysis(self, prices: dict, prepared: dict) -> None:
        """Send market analysis overview."""
        analyses = []
        for symbol, p in prices.items():
            if p["atr"] <= 0:
                continue

            pair_cfg = next((pp for pp in self.pairs if pp.symbol == symbol), None)
            if not pair_cfg:
                continue

            atr_pips = p["atr"] / pair_cfg.pip_value
            trend = "UP" if p["trend"] > 0 else ("DOWN" if p["trend"] < 0 else "FLAT")

            # Determine signal strength
            state = self.strategy.pair_states.get(symbol)
            if state and state.has_positions:
                signal = f"IN TRADE (L{state.current_level})"
                strength = state.direction.value.upper() if state.direction else ""
            else:
                if p["trend"] != 0:
                    signal = "LONG" if p["trend"] > 0 else "SHORT"
                    # Check if strategy would enter
                    allowed, reason = self.risk_manager.can_open_new(
                        symbol, self.virtual_equity, 0,
                        pd.Timestamp.now(tz="UTC"),
                        [], None
                    )
                    strength = "READY" if allowed else f"BLOCKED ({reason})"
                else:
                    signal = "WAIT"
                    strength = "no trend"

            analyses.append({
                "symbol": symbol,
                "trend": trend,
                "atr_pips": atr_pips,
                "signal": signal,
                "strength": strength,
            })

        if analyses:
            self.telegram.market_analysis(analyses)

    def _smart_sleep(self) -> None:
        """Sleep with awareness of market hours."""
        now = datetime.now(timezone.utc)
        weekday = now.weekday()

        # Weekend: sleep longer (market closed Fri 22:00 - Sun 22:00 UTC)
        if weekday == 5:  # Saturday
            sleep_until_sunday_evening = (
                timedelta(days=1, hours=22 - now.hour)
            ).total_seconds()
            sleep_time = min(sleep_until_sunday_evening, 3600)
            logger.info(f"Weekend - sleeping {sleep_time/60:.0f} min")
            time.sleep(max(60, sleep_time))
            return

        if weekday == 6 and now.hour < 22:  # Sunday before market open
            sleep_time = (22 - now.hour) * 3600
            logger.info(f"Sunday pre-market - sleeping {sleep_time/60:.0f} min")
            time.sleep(max(60, sleep_time))
            return

        # Outside session hours: check less frequently
        hour = now.hour
        if hour < self.config.grid.session_start_utc or hour >= self.config.grid.session_end_utc:
            time.sleep(CHECK_INTERVAL_SECONDS * 3)  # 15 min outside session
        else:
            time.sleep(CHECK_INTERVAL_SECONDS)  # 5 min during session

    def _save_state(self) -> None:
        """Persist state to disk for crash recovery."""
        state = {
            "virtual_equity": self.virtual_equity,
            "daily_start_equity": self._daily_start_equity,
            "last_status_time": self._last_status_time,
            "last_analysis_time": self._last_analysis_time,
            "active_positions": {},
        }

        for symbol, pair_state in self.strategy.pair_states.items():
            if pair_state.has_positions:
                state["active_positions"][symbol] = {
                    "direction": pair_state.direction.value if pair_state.direction else None,
                    "current_level": pair_state.current_level,
                    "orders": [
                        {
                            "level": o.level,
                            "entry_price": o.entry_price,
                            "lot_size": o.lot_size,
                            "entry_time": o.entry_time.isoformat(),
                            "commission": o.commission,
                        }
                        for o in pair_state.active_orders
                    ],
                    "consecutive_stops": pair_state.consecutive_stops,
                }

        try:
            with open(self._state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def _load_state(self) -> None:
        """Restore state from disk."""
        if not self._state_file.exists():
            return

        try:
            with open(self._state_file) as f:
                state = json.load(f)

            self.virtual_equity = state.get("virtual_equity", self.virtual_equity)
            self._daily_start_equity = state.get("daily_start_equity", self.virtual_equity)
            self._last_status_time = state.get("last_status_time", 0)
            self._last_analysis_time = state.get("last_analysis_time", 0)

            # Restore active positions
            for symbol, pos in state.get("active_positions", {}).items():
                pair_state = self.strategy.pair_states.get(symbol)
                if pair_state and pos.get("orders"):
                    from strategy import GridOrder
                    pair_state.direction = Direction(pos["direction"]) if pos["direction"] else None
                    pair_state.current_level = pos["current_level"]
                    pair_state.consecutive_stops = pos.get("consecutive_stops", 0)

                    for o in pos["orders"]:
                        pair_cfg = next((p for p in self.pairs if p.symbol == symbol), None)
                        if pair_cfg:
                            commission = o.get("commission",
                                               self.config.backtest.commission_per_lot * o["lot_size"])
                            order = GridOrder(
                                order_id=f"restored_{o['level']}",
                                symbol=symbol,
                                direction=pair_state.direction,
                                level=o["level"],
                                entry_price=o["entry_price"],
                                lot_size=o["lot_size"],
                                entry_time=pd.Timestamp(o["entry_time"]),
                                pip_value=pair_cfg.pip_value,
                                contract_size=pair_cfg.contract_size,
                                commission=commission,
                            )
                            pair_state.active_orders.append(order)
                            pair_state.last_order_time = order.entry_time

            logger.info(f"State restored: equity=${self.virtual_equity:.2f}, "
                        f"{sum(1 for s in self.strategy.pair_states.values() if s.has_positions)} active pairs")
        except Exception as e:
            logger.error(f"Failed to load state: {e}")

    def stop(self) -> None:
        self._running = False
