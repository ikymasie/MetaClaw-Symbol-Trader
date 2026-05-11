import pytest
import pandas as pd
from datetime import datetime, timezone
from backend.market_data_aggregator import MarketDataAggregator

def test_aggregator_zip_optimization():
    agg = MarketDataAggregator()
    # Create sample 1m data
    dates = pd.date_range(start='2020-01-01 00:00:00', periods=30, freq='1min')
    bars = []
    for i, d in enumerate(dates):
        bars.append({
            "t": d.isoformat(),
            "open": 100.0 + i,
            "high": 105.0 + i,
            "low": 95.0 + i,
            "close": 102.0 + i,
            "volume": 1000 + i
        })

    result = agg.process_symbol("EURUSD", bars)

    # Verify we get the expected timeframes
    assert "15m" in result["aggregated_bars"]

    bars_15m = result["aggregated_bars"]["15m"]
    assert len(bars_15m) == 2  # 30 mins / 15 mins = 2 bars

    # Check first 15m bar
    b0 = bars_15m[0]
    assert b0["open"] == 100.0 # First open
    assert b0["high"] == 105.0 + 14 # Max high of first 15
    assert b0["low"] == 95.0 # Min low of first 15
    assert b0["close"] == 102.0 + 14 # Last close of first 15
    assert b0["volume"] == sum([1000 + i for i in range(15)])
