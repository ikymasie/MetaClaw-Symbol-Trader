import pandas as pd
import numpy as np
import timeit

df = pd.DataFrame({'close': np.random.rand(100000) * 100 + 50})

def orig_vix():
    window = 20
    if len(df) < window + 1: return 0.0
    log_returns = np.log(df["close"] / df["close"].shift(1)).dropna()
    rolling_std = float(log_returns.rolling(window).std().iloc[-1])
    return rolling_std * (252 ** 0.5) * 100

def opt_vix():
    window = 20
    if len(df) < window + 1: return 0.0
    # We only need the last window+1 prices to get window log_returns
    last_prices = df["close"].iloc[-(window + 1):]
    log_returns = np.log(last_prices / last_prices.shift(1)).dropna()
    # We just need the std of these window returns
    rolling_std = float(log_returns.std())
    return rolling_std * (252 ** 0.5) * 100

print("orig_vix val:", orig_vix())
print("opt_vix val:", opt_vix())
print("orig_vix:", timeit.timeit(orig_vix, number=100))
print("opt_vix:", timeit.timeit(opt_vix, number=100))

def orig_vol_trend():
    short_window, long_window = 10, 30
    if len(df) < long_window + 1: return "unknown"
    log_returns = np.log(df["close"] / df["close"].shift(1)).dropna()
    vol_short = float(log_returns.rolling(short_window).std().iloc[-1])
    vol_long  = float(log_returns.rolling(long_window).std().iloc[-1])
    return vol_short / vol_long

def opt_vol_trend():
    short_window, long_window = 10, 30
    if len(df) < long_window + 1: return "unknown"
    last_prices = df["close"].iloc[-(long_window + 1):]
    log_returns = np.log(last_prices / last_prices.shift(1)).dropna()
    vol_short = float(log_returns.iloc[-short_window:].std())
    vol_long  = float(log_returns.std())
    return vol_short / vol_long

print("orig_vol_trend val:", orig_vol_trend())
print("opt_vol_trend val:", opt_vol_trend())
print("orig_vol_trend:", timeit.timeit(orig_vol_trend, number=100))
print("opt_vol_trend:", timeit.timeit(opt_vol_trend, number=100))
