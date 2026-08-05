import pandas as pd
import numpy as np
import timeit

df = pd.DataFrame({'close': np.random.rand(100000) * 100 + 50})
prices = df['close']

def orig_rvol():
    lookback = 20
    if len(prices) < lookback:
        return None
    vol = df["close"] * 10 # dummy volume
    mean_vol = vol.rolling(window=lookback).mean()
    if mean_vol.iloc[-1] == 0:
        return 1.0
    return float(vol.iloc[-1] / mean_vol.iloc[-1])

def opt_rvol():
    lookback = 20
    if len(prices) < lookback:
        return None
    vol = df["close"] * 10 # dummy volume
    last_vols = vol.iloc[-lookback:]
    mean_vol = last_vols.mean()
    if mean_vol == 0:
        return 1.0
    return float(vol.iloc[-1] / mean_vol)

print("orig_rvol val:", orig_rvol())
print("opt_rvol val:", opt_rvol())
print("orig_rvol:", timeit.timeit(orig_rvol, number=100))
print("opt_rvol:", timeit.timeit(opt_rvol, number=100))
