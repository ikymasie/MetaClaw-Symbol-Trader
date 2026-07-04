"""
TradeClaw — Market Data Aggregator
====================================
Aggregates 1-minute bars into higher timeframes (15m, 1h, 1d, 1wk, 1mo)
and computes market trend summaries (regime, momentum, volatility).

Uses pandas for efficient resampling and RegimeDetector for trend analysis.
"""

import logging
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from regime_detector import RegimeDetector

logger = logging.getLogger("tradeclaw.aggregator")

class MarketDataAggregator:
    def __init__(self):
        self.regime_detector = RegimeDetector()
        # Mapping timeframe strings to pandas frequency strings
        self.tf_map = {
            "15m": "15min",
            "1h": "h",
            "1d": "d",
            "1wk": "W",
            "1mo": "ME"
        }
        # Phase 3 §9.2 — Delta-processing cache keyed by symbol.
        # Skips full pandas aggregation when the newest 1m bar timestamp is
        # unchanged since the last process_symbol() call for that symbol.
        self._last_bar_timestamps: Dict[str, str] = {}
        self._last_results: Dict[str, dict] = {}

    def aggregate(self, df_1m: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """
        Aggregate 1m bars into the target timeframe.
        df_1m must have a DatetimeIndex and columns: open, high, low, close, volume.
        """
        if timeframe not in self.tf_map:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        
        freq = self.tf_map[timeframe]
        
        # Resample logic
        # 't' is our timestamp field, but we assume df_1m index is already datetime
        resampled = df_1m.resample(freq, label='left', closed='left').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        
        return resampled

    def compute_trend_summary(self, df: pd.DataFrame, symbol: str, timeframe: str) -> dict:
        """
        Compute a trend summary for a given timeframe's data.
        """
        state = self.regime_detector.detect(df)
        
        # Additional metrics: RSI, Moving Averages
        close = df['close']
        ma_20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else None
        ma_50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
        
        # Simple RSI calculation
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = float(100 - (100 / (1 + rs)).iloc[-1]) if len(close) >= 15 else None

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "regime": state.regime,
            "trend_direction": state.trend_direction,
            "adx": state.adx,
            "atr_zscore": state.atr_zscore,
            "rsi": rsi,
            "ma_20": ma_20,
            "ma_50": ma_50,
            "can_mean_revert": state.can_mean_revert,
            "confidence": state.confidence,
            "reason": state.reason,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def process_symbol(self, symbol: str, bars_1m: list[dict]) -> dict:
        """
        Perform full multi-timeframe aggregation and trend analysis for a symbol.

        Phase 3 enhancements:
          §9.1 — Adds raw pandas DataFrames under a "dataframes" key for
                 in-process consumers (e.g. CorrelationAgent). These are NOT
                 serialised; callers must strip the key before persisting.
          §9.2 — Stateful caching: if the newest 1m bar timestamp matches the
                 previous call for this symbol, returns the cached result
                 instead of recomputing.

        Returns:
            {
                "aggregated_bars":  { "15m": [...], "1h": [...], ... },
                "trend_summaries":  { "1m": {...}, "15m": {...}, ... },
                "dataframes":       { "1m": pd.DataFrame, "15m": pd.DataFrame, ... },  # in-process only
            }
        """
        if not bars_1m:
            return {}

        # ── Cache fast-path (Phase 3 §9.2) ───────────────────────────────
        # Probe the newest bar's timestamp BEFORE any pandas allocation.
        _latest = bars_1m[-1]
        latest_ts_raw = _latest.get("t") or _latest.get("time") or _latest.get("timestamp")
        if latest_ts_raw is not None:
            latest_key = str(latest_ts_raw)
            if latest_key == self._last_bar_timestamps.get(symbol):
                cached = self._last_results.get(symbol)
                if cached:
                    return cached

        df_1m = pd.DataFrame(bars_1m)

        # Normalize timestamp field
        if 'time' in df_1m.columns and 't' not in df_1m.columns:
            df_1m.rename(columns={'time': 't'}, inplace=True)
        elif 'timestamp' in df_1m.columns and 't' not in df_1m.columns:
            df_1m.rename(columns={'timestamp': 't'}, inplace=True)

        # Convert timestamp strings to datetime
        if 't' not in df_1m.columns:
            logger.warning(f"No timestamp column found for {symbol}. Columns: {df_1m.columns}")
            return {}

        df_1m['t'] = pd.to_datetime(df_1m['t'])
        df_1m.set_index('t', inplace=True)

        # Normalise short-form field names (o/h/l/c/v) used by BotEngine
        # to the long-form names (open/high/low/close/volume) expected by
        # pandas resampling and indicator calculations.
        _rename = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
        df_1m.rename(columns={k: v for k, v in _rename.items() if k in df_1m.columns},
                     inplace=True)

        # Ensure numeric columns
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df_1m.columns:
                df_1m[col] = pd.to_numeric(df_1m[col], errors='coerce')

        # Drop non-OHLCV columns (e.g. 'src' metadata) and NaN rows
        _keep = [c for c in ['open', 'high', 'low', 'close', 'volume'] if c in df_1m.columns]
        df_1m = df_1m[_keep].dropna(subset=['close'])

        if df_1m.empty:
            return {}

        # Phase 3 §9.1 — include raw DataFrames keyed by timeframe for
        # in-process consumers (e.g. CorrelationAgent, future agents).
        result = {
            "aggregated_bars": {},
            "trend_summaries": {},
            "dataframes": {"1m": df_1m},
        }

        # 1m Trend Summary
        result["trend_summaries"]["1m"] = self.compute_trend_summary(df_1m, symbol, "1m")

        # Higher timeframes
        for tf in self.tf_map:
            try:
                df_tf = self.aggregate(df_1m, tf)
                if df_tf.empty:
                    continue

                # Convert back to list of dicts for Firestore
                # ⚡ Bolt: Using zip() instead of df.iterrows() to avoid Pandas Series boxing overhead
                bars_tf = [
                    {
                        "t": ts.isoformat(),
                        "open": float(o),
                        "high": float(h),
                        "low": float(l),
                        "close": float(c),
                        "volume": float(v)
                    }
                    for ts, o, h, l, c, v in zip(
                        df_tf.index,
                        df_tf["open"],
                        df_tf["high"],
                        df_tf["low"],
                        df_tf["close"],
                        df_tf["volume"]
                    )
                ]

                result["aggregated_bars"][tf] = bars_tf
                result["trend_summaries"][tf] = self.compute_trend_summary(df_tf, symbol, tf)
                result["dataframes"][tf] = df_tf
            except Exception as e:
                logger.error(f"Error processing timeframe {tf} for {symbol}: {e}")

        # ── Update cache (Phase 3 §9.2) ──────────────────────────────────
        if latest_ts_raw is not None:
            self._last_bar_timestamps[symbol] = str(latest_ts_raw)
            self._last_results[symbol] = result

        return result
