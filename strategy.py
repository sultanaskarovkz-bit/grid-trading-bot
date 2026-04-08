"""
Core grid trading strategy — v2.
Per-pair basket management with individual TP/SL, adaptive cooldowns,
and portfolio-level risk controls.
"""

import logging
import uuid
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from config import Direction, GridConfig, PairConfig
from risk_manager import RiskManager

logger = logging.getLogger(__name__)


@dataclass
class GridOrder:
    """Represents a single grid order."""
    order_id: str
    symbol: str
    direction: Direction
    level: int
    entry_price: float
    lot_size: float
    entry_time: pd.Timestamp
    pip_value: float
    contract_size: float = 100_000.0
    unrealized_pnl: float = 0.0
    commission: float = 0.0

    def update_pnl(self, current_price: float) -> float:
        """Calculate unrealized P&L in USD."""
        if self.direction == Direction.LONG:
            price_diff = current_price - self.entry_price
        else:
            price_diff = self.entry_price - current_price

        self.unrealized_pnl = price_diff * self.contract_size * self.lot_size - self.commission
        return self.unrealized_pnl


@dataclass
class PairState:
    """Tracks the grid state for a single currency pair."""
    symbol: str
    pair_config: PairConfig
    direction: Direction | None = None
    active_orders: list = field(default_factory=list)
    last_order_time: pd.Timestamp | None = None
    current_level: int = 0
    total_closed_pnl: float = 0.0
    # Per-pair cooldown after individual stop
    last_stop_time: pd.Timestamp | None = None
    consecutive_stops: int = 0
    peak_basket_pnl: float = 0.0  # for trailing stop

    @property
    def has_positions(self) -> bool:
        return len(self.active_orders) > 0

    @property
    def basket_pnl(self) -> float:
        return sum(o.unrealized_pnl for o in self.active_orders)

    @property
    def total_lots(self) -> float:
        return sum(o.lot_size for o in self.active_orders)

    @property
    def avg_entry_price(self) -> float:
        if not self.active_orders:
            return 0.0
        total_cost = sum(o.entry_price * o.lot_size for o in self.active_orders)
        total_lots = self.total_lots
        return total_cost / total_lots if total_lots > 0 else 0.0

    def last_entry_price(self) -> float:
        if not self.active_orders:
            return 0.0
        return self.active_orders[-1].entry_price

    def reset(self) -> None:
        """Clear all positions after basket close."""
        self.active_orders = []
        self.last_order_time = None
        self.current_level = 0
        self.direction = None
        self.peak_basket_pnl = 0.0


@dataclass
class TradeRecord:
    """Record of a completed basket trade."""
    close_time: pd.Timestamp
    symbols: list
    direction: str
    num_levels: int
    total_lots: float
    pnl: float
    holding_time_hours: float
    equity_after: float


class GridStrategy:
    """
    Multi-currency adaptive grid strategy v2.

    Key improvements over v1:
    - Per-pair basket TP/SL (close each pair independently)
    - Trailing take profit per pair
    - Adaptive cooldown (increases after consecutive stops)
    - Portfolio hard stop only as emergency
    """

    def __init__(self, config: GridConfig, risk_manager: RiskManager,
                 pairs: list[PairConfig], commission_per_lot: float = 7.0):
        self.config = config
        self.risk_manager = risk_manager
        self.commission_per_lot = commission_per_lot
        self.pair_states: dict[str, PairState] = {}
        self.trade_history: list[TradeRecord] = []

        # Per-pair risk parameters (derived from portfolio-level config)
        self._pair_tp_pct = config.fix_take_profit_pct  # % of equity per pair basket
        self._pair_sl_pct = config.stop_drawdown_pct / 3  # individual pair SL
        self._trailing_activation_pct = config.fix_take_profit_pct * 0.6  # activate trailing at 60% of TP
        self._trailing_distance_pct = config.fix_take_profit_pct * 0.4  # trail by 40% of TP
        self._base_cooldown_hours = config.base_cooldown_hours if hasattr(config, 'base_cooldown_hours') else 2
        self._max_cooldown_hours = config.max_cooldown_hours if hasattr(config, 'max_cooldown_hours') else 24
        self._max_simultaneous_pairs = config.max_simultaneous_pairs if hasattr(config, 'max_simultaneous_pairs') else 5

        for pair in pairs:
            self.pair_states[pair.symbol] = PairState(
                symbol=pair.symbol,
                pair_config=pair,
            )

    def on_bar(self, timestamp: pd.Timestamp,
               prices: dict[str, dict],
               equity: float,
               correlation_matrix: pd.DataFrame | None = None) -> list[dict]:
        """
        Main entry point — called once per bar.
        equity: REALIZED equity (not including unrealized P&L)
        """
        actions = []

        # 1. Update P&L for all active orders
        total_basket_pnl = 0.0
        for symbol, state in self.pair_states.items():
            if not state.has_positions:
                continue
            if symbol not in prices:
                continue
            current_price = prices[symbol]["close"]
            for order in state.active_orders:
                order.update_pnl(current_price)

            # Update per-pair peak PnL for trailing stop
            if state.basket_pnl > state.peak_basket_pnl:
                state.peak_basket_pnl = state.basket_pnl

            total_basket_pnl += state.basket_pnl

        effective_equity = equity + total_basket_pnl
        self.risk_manager.update_peak_equity(effective_equity)

        # 2. Check PORTFOLIO-level hard stop (emergency only)
        if self.risk_manager.check_hard_stop(effective_equity):
            close_actions = self._close_all_baskets(timestamp, prices, "HARD_STOP")
            for state in self.pair_states.values():
                state.consecutive_stops += 1
                state.last_stop_time = timestamp
            actions.extend(close_actions)
            return actions

        # 3. Check PER-PAIR basket TP/SL
        for symbol, state in self.pair_states.items():
            if not state.has_positions:
                continue
            if symbol not in prices:
                continue

            pair_pnl = state.basket_pnl
            pair_pnl_pct = (pair_pnl / max(effective_equity, 100)) * 100

            # Per-pair take profit
            if pair_pnl_pct >= self._pair_tp_pct:
                close_action = self._close_pair_basket(
                    state, timestamp, prices[symbol]["close"], "TAKE_PROFIT"
                )
                state.consecutive_stops = 0  # reset on win
                actions.append(close_action)
                continue

            # Trailing stop: if we reached activation level and then pulled back
            if state.peak_basket_pnl > 0:
                peak_pct = (state.peak_basket_pnl / max(effective_equity, 100)) * 100
                if peak_pct >= self._trailing_activation_pct:
                    # Trail by fixed percentage of peak PnL
                    trail_level = state.peak_basket_pnl * (1 - self._trailing_distance_pct / self._pair_tp_pct)
                    if pair_pnl < trail_level and pair_pnl > 0:
                        close_action = self._close_pair_basket(
                            state, timestamp, prices[symbol]["close"], "TRAILING_TP"
                        )
                        state.consecutive_stops = 0
                        actions.append(close_action)
                        continue

            # Per-pair stop loss
            if pair_pnl_pct <= -self._pair_sl_pct:
                close_action = self._close_pair_basket(
                    state, timestamp, prices[symbol]["close"], "PAIR_STOP"
                )
                state.consecutive_stops += 1
                state.last_stop_time = timestamp
                actions.append(close_action)
                continue

        # 4. Check each pair for new grid entries
        active_symbols_dirs = [
            (sym, state.direction.value if state.direction else "none")
            for sym, state in self.pair_states.items()
            if state.has_positions
        ]

        active_pair_count = sum(1 for s in self.pair_states.values() if s.has_positions)

        for symbol, state in self.pair_states.items():
            if symbol not in prices:
                continue

            # Per-pair adaptive cooldown after stops
            if state.last_stop_time is not None:
                cooldown = self._base_cooldown_hours * (2 ** min(state.consecutive_stops, 4))
                cooldown = min(cooldown, self._max_cooldown_hours)
                hours_since_stop = (timestamp - state.last_stop_time).total_seconds() / 3600
                if hours_since_stop < cooldown:
                    continue

            # Max simultaneous new pairs
            if not state.has_positions and active_pair_count >= self._max_simultaneous_pairs:
                continue

            price_data = prices[symbol]
            entry_action = self._check_grid_entry(
                state, price_data, timestamp, effective_equity,
                active_symbols_dirs, correlation_matrix
            )
            if entry_action:
                actions.append(entry_action)
                if not state.has_positions:
                    active_pair_count += 1
                active_symbols_dirs.append(
                    (symbol, state.direction.value if state.direction else "none")
                )

        return actions

    def _check_grid_entry(self, state: PairState, price_data: dict,
                          timestamp: pd.Timestamp, equity: float,
                          active_symbols_dirs: list[tuple[str, str]],
                          correlation_matrix: pd.DataFrame | None) -> dict | None:
        """Check if a new grid level should be opened for this pair."""
        symbol = state.symbol
        current_price = price_data["close"]
        atr_value = price_data.get("atr", 0.0)
        trend = price_data.get("trend", 0)

        if atr_value is None or (isinstance(atr_value, float) and np.isnan(atr_value)) or atr_value <= 0:
            return None

        # --- Level 0: Initial entry ---
        if not state.has_positions:
            allowed, reason = self.risk_manager.can_open_new(
                symbol, equity, 0, timestamp,
                active_symbols_dirs, correlation_matrix
            )
            if not allowed:
                return None

            # Determine direction from trend filter
            if self.config.trend_filter_enabled:
                if trend == 0:
                    return None
                direction = Direction.LONG if trend > 0 else Direction.SHORT
            else:
                direction = Direction.LONG

            lot_size = self.risk_manager.calculate_position_size(
                symbol, equity, 0, atr_value
            )

            return self._create_open_action(
                state, direction, current_price, lot_size, timestamp, 0
            )

        # --- Level N > 0: Grid continuation ---
        time_delay = self.config.get_time_delay(state.current_level)
        if state.last_order_time is not None:
            elapsed = (timestamp - state.last_order_time).total_seconds()
            if elapsed < time_delay:
                return None

        # ATR-adaptive grid distance
        grid_distance_pips = self.config.get_grid_distance_pips(state.current_level)
        atr_pips = atr_value / state.pair_config.pip_value
        # Use ATR to scale the fixed distance
        atr_factor = self.config.atr_multiplier * (atr_pips / max(atr_pips, 1))
        actual_distance_pips = grid_distance_pips * max(0.5, min(atr_factor, 2.0))
        actual_distance_price = actual_distance_pips * state.pair_config.pip_value

        last_price = state.last_entry_price()
        price_moved = abs(current_price - last_price)

        if price_moved < actual_distance_price:
            return None

        # Verify price moved AGAINST our position
        if state.direction == Direction.LONG and current_price >= last_price:
            return None
        if state.direction == Direction.SHORT and current_price <= last_price:
            return None

        # Risk check
        allowed, reason = self.risk_manager.can_open_new(
            symbol, equity, state.current_level, timestamp,
            active_symbols_dirs, correlation_matrix
        )
        if not allowed:
            return None

        lot_size = self.risk_manager.calculate_position_size(
            symbol, equity, state.current_level, atr_value
        )

        return self._create_open_action(
            state, state.direction, current_price, lot_size,
            timestamp, state.current_level
        )

    def _create_open_action(self, state: PairState, direction: Direction,
                            price: float, lot_size: float,
                            timestamp: pd.Timestamp, level: int) -> dict:
        """Create an order and return the action dict."""
        spread = state.pair_config.spread_pips * state.pair_config.pip_value
        if direction == Direction.LONG:
            entry_price = price + spread / 2
        else:
            entry_price = price - spread / 2

        commission = self.commission_per_lot * lot_size

        order = GridOrder(
            order_id=str(uuid.uuid4())[:8],
            symbol=state.symbol,
            direction=direction,
            level=level,
            entry_price=entry_price,
            lot_size=lot_size,
            entry_time=timestamp,
            pip_value=state.pair_config.pip_value,
            contract_size=state.pair_config.contract_size,
            commission=commission,
        )

        state.active_orders.append(order)
        state.direction = direction
        state.last_order_time = timestamp
        state.current_level = level + 1

        logger.debug(
            f"OPEN {direction.value} {state.symbol} L{level} "
            f"@ {entry_price:.5f} x {lot_size} lots"
        )

        return {
            "action": "open",
            "symbol": state.symbol,
            "direction": direction.value,
            "level": level,
            "price": entry_price,
            "lot_size": lot_size,
            "timestamp": timestamp,
            "order_id": order.order_id,
            "commission": commission,
        }

    def _close_pair_basket(self, state: PairState, timestamp: pd.Timestamp,
                           close_price: float, reason: str) -> dict:
        """Close all orders for a single pair."""
        basket_pnl = state.basket_pnl
        earliest_entry = min(o.entry_time for o in state.active_orders)
        holding_hours = (timestamp - earliest_entry).total_seconds() / 3600

        self.trade_history.append(TradeRecord(
            close_time=timestamp,
            symbols=[state.symbol],
            direction=state.direction.value if state.direction else "none",
            num_levels=len(state.active_orders),
            total_lots=state.total_lots,
            pnl=basket_pnl,
            holding_time_hours=holding_hours,
            equity_after=0,
        ))

        action = {
            "action": "close_basket",
            "symbol": state.symbol,
            "reason": reason,
            "pnl": basket_pnl,
            "num_orders": len(state.active_orders),
            "timestamp": timestamp,
            "close_price": close_price,
        }

        logger.info(
            f"CLOSE {state.symbol} ({reason}): "
            f"{len(state.active_orders)} levels, PnL: {basket_pnl:.2f}"
        )

        state.total_closed_pnl += basket_pnl
        state.reset()
        return action

    def _close_all_baskets(self, timestamp: pd.Timestamp,
                           prices: dict[str, dict],
                           reason: str) -> list[dict]:
        """Close ALL positions across ALL pairs (emergency)."""
        actions = []
        total_pnl = 0.0

        for symbol, state in self.pair_states.items():
            if not state.has_positions:
                continue
            close_price = prices.get(symbol, {}).get("close", 0)
            action = self._close_pair_basket(state, timestamp, close_price, reason)
            total_pnl += action["pnl"]
            actions.append(action)

        if actions:
            # Reset peak equity so bot can resume
            self.risk_manager.peak_equity = 0.0
            logger.info(f"PORTFOLIO CLOSE ({reason}) at {timestamp}: total PnL: {total_pnl:.2f}")

        return actions

    def get_portfolio_state(self) -> dict:
        """Current portfolio summary."""
        total_pnl = 0.0
        total_lots = 0.0
        active_pairs = 0

        for state in self.pair_states.values():
            if state.has_positions:
                active_pairs += 1
                total_pnl += state.basket_pnl
                total_lots += state.total_lots

        return {
            "active_pairs": active_pairs,
            "total_unrealized_pnl": total_pnl,
            "total_lots": total_lots,
            "total_closed_pnl": sum(s.total_closed_pnl for s in self.pair_states.values()),
            "trade_count": len(self.trade_history),
        }
