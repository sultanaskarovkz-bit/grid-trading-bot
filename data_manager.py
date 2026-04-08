"""
Data management layer — abstracts data loading for backtesting (yfinance) and live (MT5).
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# yfinance ticker mapping for Forex pairs
YFINANCE_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "EURCHF": "EURCHF=X",
    "EURJPY": "EURJPY=X",
    "USDCHF": "USDCHF=X",
    "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X",
    "NZDUSD": "NZDUSD=X",
    "USDCAD": "USDCAD=X",
}


class DataManager:
    """Loads, caches, and validates OHLCV data for multiple pairs."""

    def __init__(self, cache_dir: str = "data_cache"):
        self._cache: dict[str, pd.DataFrame] = {}
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(exist_ok=True)

    def load_pair_yfinance(self, symbol: str, timeframe: str,
                           start: str, end: str) -> pd.DataFrame:
        """Load data from yfinance with disk caching.
        For intraday timeframes, yfinance limits to 730 days.
        Automatically adjusts date range and downloads in chunks if needed.
        """
        cache_key = f"{symbol}_{timeframe}_{start}_{end}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        cache_file = self._cache_dir / f"{cache_key}.csv"
        if cache_file.exists():
            df = pd.read_csv(cache_file, index_col="datetime", parse_dates=True)
            self._cache[cache_key] = df
            logger.info(f"Loaded {symbol} from cache: {len(df)} bars")
            return df

        import yfinance as yf
        from datetime import datetime, timedelta

        ticker = YFINANCE_MAP.get(symbol, f"{symbol}=X")

        # yfinance intraday data limit: ~730 days
        intraday_tfs = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"}
        requested_start = pd.Timestamp(start)
        requested_end = pd.Timestamp(end)

        if timeframe in intraday_tfs:
            max_days = 729
            now = pd.Timestamp.now()
            earliest_allowed = now - timedelta(days=max_days)

            if requested_start < earliest_allowed:
                logger.warning(
                    f"{symbol}: yfinance limits {timeframe} data to {max_days} days. "
                    f"Adjusting start from {start} to {earliest_allowed.date()}"
                )
                requested_start = earliest_allowed

            if requested_end > now:
                requested_end = now

        logger.info(f"Downloading {symbol} ({ticker}) from yfinance "
                     f"({requested_start.date()} to {requested_end.date()})...")

        raw = yf.download(
            ticker,
            start=requested_start.strftime("%Y-%m-%d"),
            end=requested_end.strftime("%Y-%m-%d"),
            interval=timeframe,
            progress=False, auto_adjust=True,
        )

        if raw.empty:
            raise ValueError(f"No data returned for {symbol} ({ticker})")

        # Handle MultiIndex columns from yfinance
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        df = pd.DataFrame({
            "open": raw["Open"].values,
            "high": raw["High"].values,
            "low": raw["Low"].values,
            "close": raw["Close"].values,
            "volume": raw["Volume"].values if "Volume" in raw.columns else 0,
        }, index=raw.index)

        df.index.name = "datetime"
        df = df.ffill()  # forward-fill small gaps first
        df = df.dropna()  # then remove rows that still have NaN

        if df.empty:
            raise ValueError(f"No valid data for {symbol} after cleaning")

        # Validate no all-zero or constant data
        if (df["close"] == 0).any():
            df = df[df["close"] > 0]

        if len(df) < 50:
            raise ValueError(f"Insufficient data for {symbol}: only {len(df)} bars (need 50+)")

        df.to_csv(cache_file)
        self._cache[cache_key] = df
        logger.info(f"Downloaded {symbol}: {len(df)} bars ({df.index[0]} to {df.index[-1]})")
        return df

    def load_all_pairs(self, symbols: list[str], timeframe: str,
                       start: str, end: str) -> dict[str, pd.DataFrame]:
        """Load data for multiple pairs."""
        data = {}
        for symbol in symbols:
            try:
                data[symbol] = self.load_pair_yfinance(symbol, timeframe, start, end)
            except Exception as e:
                logger.error(f"Failed to load {symbol}: {e}")
        return data

    def align_data(self, data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        """Align all pairs to a common datetime index (intersection)."""
        if not data:
            return data

        common_index = None
        for df in data.values():
            if common_index is None:
                common_index = df.index
            else:
                common_index = common_index.intersection(df.index)

        aligned = {}
        for symbol, df in data.items():
            aligned[symbol] = df.loc[common_index].copy()

        logger.info(f"Aligned {len(data)} pairs to {len(common_index)} common bars")
        return aligned
