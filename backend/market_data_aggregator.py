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
        Returns:
            {
                "aggregated_bars": { "15m": [...], "1h": [...], ... },
                "trend_summaries": { "1m": {...}, "15m": {...}, ... }
            }
        """
        if not bars_1m:
            return {}

        df_1m = pd.DataFrame(bars_1m)
        # Convert timestamp strings to datetime
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

        result = {
            "aggregated_bars": {},
            "trend_summaries": {}
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

                # Optimize dataframe to dict conversion using vectorized operations
                # replacing slow iterrows() loop

                # Format datetime index to ISO format
                df_tf_copy = df_tf.copy()
                df_tf_copy['t'] = df_tf_copy.index.map(lambda x: x.isoformat())

                # Keep only required columns and convert to list of dicts
                cols = ['t', 'open', 'high', 'low', 'close', 'volume']
                # Ensure float type for numeric columns (should already be numeric, but ensures float conversion)
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df_tf_copy[col] = df_tf_copy[col].astype(float)

                bars_tf = df_tf_copy[cols].to_dict('records')
                
                result["aggregated_bars"][tf] = bars_tf
                result["trend_summaries"][tf] = self.compute_trend_summary(df_tf, symbol, tf)
            except Exception as e:
                logger.error(f"Error processing timeframe {tf} for {symbol}: {e}")

        return result
