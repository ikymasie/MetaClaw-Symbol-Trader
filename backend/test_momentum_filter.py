
import pytest
import pandas as pd
import numpy as np
from backend.momentum_filter import (
    MomentumFilter,
    MomentumState,
    MOMENTUM_BULLISH,
    MOMENTUM_BEARISH,
    MOMENTUM_NEUTRAL,
    DEFAULT_EMA_FAST,
    DEFAULT_EMA_MID,
    DEFAULT_EMA_SLOW,
)

def create_mock_df(prices):
    return pd.DataFrame({"close": prices})

def test_insufficient_data():
    mf = MomentumFilter()
    df = create_mock_df([100.0] * 10)
    state = mf.assess(df)

    assert state.alignment == MOMENTUM_NEUTRAL
    assert "Insufficient data" in state.reason
    assert state.ema_fast == 0.0
    assert state.size_multiplier == 0.5
    assert state.allows_long is True

def test_bullish_alignment():
    # Construct prices that should lead to EF > EM > ES
    # Using enough data for EMAs to stabilize
    # Price trending up
    prices = [100.0 + i for i in range(100)]
    df = create_mock_df(prices)
    mf = MomentumFilter(ema_fast=8, ema_mid=21, ema_slow=55)
    state = mf.assess(df)

    assert state.alignment == MOMENTUM_BULLISH
    assert state.ema_fast > state.ema_mid > state.ema_slow
    assert state.allows_long is True
    assert state.size_multiplier == 1.0
    assert "BULLISH STACK" in state.reason

def test_bearish_alignment():
    # Price trending down
    prices = [100.0 - i for i in range(100)]
    df = create_mock_df(prices)
    mf = MomentumFilter(ema_fast=8, ema_mid=21, ema_slow=55)
    state = mf.assess(df)

    assert state.alignment == MOMENTUM_BEARISH
    assert state.ema_fast < state.ema_mid < state.ema_slow
    assert state.allows_long is False
    assert state.size_multiplier == 0.0
    assert "BEARISH STACK" in state.reason

def test_neutral_alignment():
    # Construct a flat then volatile price to get mixed EMAs
    # Fast might be above mid, but mid below slow, etc.
    # Start with 60 periods of 100
    prices = [100.0] * 60
    # Suddenly drop fast, then bounce a bit
    prices.extend([90.0, 95.0, 92.0])

    df = create_mock_df(prices)
    mf = MomentumFilter(ema_fast=8, ema_mid=21, ema_slow=55)
    state = mf.assess(df)

    # We expect neutral if they are not perfectly stacked
    # ef will be around 92-95, em around 98, es around 99
    assert state.alignment == MOMENTUM_NEUTRAL
    assert not (state.ema_fast > state.ema_mid > state.ema_slow)
    assert not (state.ema_fast < state.ema_mid < state.ema_slow)
    assert state.allows_long is True
    assert state.size_multiplier == 0.5
    assert "NEUTRAL" in state.reason

def test_golden_cross():
    # Golden cross: Fast crosses above Mid
    # Initially Fast < Mid, then Fast > Mid

    # Base prices to stabilize
    prices = [100.0] * 60
    # Fast is 8, Mid is 21.
    # Let's make Fast drop below Mid, then cross above.
    # Actually, if price is flat, they are equal.

    # Start with a downtrend to put Fast below Mid
    prices = [110.0 - (i * 0.1) for i in range(100)]
    # ef < em < es (Bearish)

    # Now pump the price
    prices.extend([115.0] * 20)

    df = create_mock_df(prices)
    mf = MomentumFilter(ema_fast=8, ema_mid=21, ema_slow=55)

    # We want to find the exact point of crossover.
    # We can iterate through the last few bars.
    found_cross = False
    for i in range(60, len(prices) + 1):
        sub_df = create_mock_df(prices[:i])
        state = mf.assess(sub_df)
        if state.crossover_event == "FAST_CROSS_MID_UP":
            found_cross = True
            break

    assert found_cross is True

def test_death_cross():
    # Death cross: Fast crosses below Mid

    # Initially uptrend
    prices = [100.0 + (i * 0.1) for i in range(100)]
    # Now dump the price
    prices.extend([90.0] * 20)

    df = create_mock_df(prices)
    mf = MomentumFilter(ema_fast=8, ema_mid=21, ema_slow=55)

    found_cross = False
    for i in range(60, len(prices) + 1):
        sub_df = create_mock_df(prices[:i])
        state = mf.assess(sub_df)
        if state.crossover_event == "FAST_CROSS_MID_DOWN":
            found_cross = True
            break

    assert found_cross is True

def test_parameter_overrides():
    prices = [100.0 + i for i in range(100)]
    df = create_mock_df(prices)
    mf = MomentumFilter(ema_fast=20, ema_mid=40, ema_slow=60)

    # Assess with defaults (20, 40, 60)
    state_default = mf.assess(df)

    # Assess with overrides (8, 21, 55)
    state_override = mf.assess(df, ema_fast_override=8, ema_mid_override=21, ema_slow_override=55)

    assert state_override.ema_fast != state_default.ema_fast
    # Fast 8 will react quicker to the uptrend than Fast 20
    assert state_override.ema_fast > state_default.ema_fast

def test_error_handling_missing_column():
    mf = MomentumFilter()
    df = pd.DataFrame({"not_close": [1, 2, 3] * 20})
    state = mf.assess(df)

    assert state.alignment == MOMENTUM_NEUTRAL
    assert "Assessment error" in state.reason
    assert "close" in state.reason

def test_get_last_state():
    mf = MomentumFilter()
    df = create_mock_df([100.0] * 100)
    state = mf.assess(df)

    last_state = mf.get_last_state()
    assert last_state == state

def test_momentum_state_to_dict():
    state = MomentumState(
        alignment=MOMENTUM_BULLISH,
        ema_fast=10.123456,
        ema_mid=9.123456,
        ema_slow=8.123456,
        crossover_event="NONE",
        allows_long=True,
        size_multiplier=1.0,
        reason="Test reason"
    )
    d = state.to_dict()
    assert d["alignment"] == MOMENTUM_BULLISH
    assert d["ema_fast"] == 10.1235 # Rounded to 4
    assert d["allows_long"] is True
