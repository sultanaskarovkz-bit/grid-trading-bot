"""
Technical indicators for the grid trading bot.
All methods are stateless and operate on pandas DataFrames/Series.
"""

import numpy as np
import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range — used for adaptive grid spacing."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    return tr.ewm(span=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, min_periods=period).mean()


def compute_trend(close: pd.Series, fast: int, slow: int) -> pd.Series:
    """Returns +1 for uptrend (fast > slow), -1 for downtrend."""
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    trend = pd.Series(0, index=close.index, dtype=int)
    trend[ema_fast > ema_slow] = 1
    trend[ema_fast < ema_slow] = -1
    return trend


def correlation_matrix(price_dict: dict, window: int = 100) -> pd.DataFrame:
    """
    Compute rolling correlation matrix between pairs.
    price_dict: {symbol: pd.Series of close prices}
    Returns the most recent correlation matrix.
    """
    if len(price_dict) < 2:
        symbols = list(price_dict.keys())
        return pd.DataFrame(0.0, index=symbols, columns=symbols)

    returns = pd.DataFrame({
        sym: prices.pct_change() for sym, prices in price_dict.items()
    })
    return returns.tail(window).corr()


def compute_indicators(df: pd.DataFrame, atr_period: int = 14,
                        ema_fast: int = 50, ema_slow: int = 200) -> pd.DataFrame:
    """Add all indicator columns to a price DataFrame."""
    if df is None or df.empty:
        return df

    # Ensure ema_fast < ema_slow
    if ema_fast >= ema_slow:
        ema_fast, ema_slow = min(ema_fast, ema_slow), max(ema_fast, ema_slow)

    df = df.copy()
    df["atr"] = atr(df, atr_period)
    df["ema_fast"] = ema(df["close"], ema_fast)
    df["ema_slow"] = ema(df["close"], ema_slow)
    df["trend"] = compute_trend(df["close"], ema_fast, ema_slow)

    # Fill NaN in indicators with safe defaults
    df["atr"] = df["atr"].fillna(0.0)
    df["trend"] = df["trend"].fillna(0).astype(int)

    return df
