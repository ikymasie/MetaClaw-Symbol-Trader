from market_data_aggregator import MarketDataAggregator

def test_aggregate_zip():
    agg = MarketDataAggregator()
    # Create sample data
    bars_1m = [
        {
            "t": "2024-01-01T00:00:00Z",
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 102.0,
            "volume": 1000
        },
        {
            "t": "2024-01-01T00:01:00Z",
            "open": 102.0,
            "high": 108.0,
            "low": 101.0,
            "close": 107.0,
            "volume": 1500
        }
    ]
    result = agg.process_symbol("TEST", bars_1m)

    assert "aggregated_bars" in result
    assert "15m" in result["aggregated_bars"]

    bar_15m = result["aggregated_bars"]["15m"][0]
    assert bar_15m["open"] == 100.0
    assert bar_15m["high"] == 108.0
    assert bar_15m["low"] == 95.0
    assert bar_15m["close"] == 107.0
    assert bar_15m["volume"] == 2500

    print("Test passed successfully!")
