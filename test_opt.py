import pandas as pd
import numpy as np
import timeit

# Generate large dataframe
df = pd.DataFrame({'close': np.random.rand(100000) * 100 + 50})
close = df['close']

def orig():
    if len(close) >= 20:
        ma_20 = float(close.rolling(20).mean().iloc[-1])

def opt():
    if len(close) >= 20:
        ma_20 = float(close.iloc[-20:].mean())

print("orig:", timeit.timeit(orig, number=100))
print("opt:", timeit.timeit(opt, number=100))

# Also RSI
def orig_rsi():
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = float(100 - (100 / (1 + rs)).iloc[-1]) if len(close) >= 15 else None
    return rsi

def opt_rsi():
    delta = close.diff()
    # To be exactly equivalent:
    # Orig calculates delta over whole, then gain/loss over whole
    last_delta = delta.iloc[-14:]
    gain = last_delta[last_delta > 0].sum() / 14.0 # same as where(x>0,0).mean() since len=14
    loss = -last_delta[last_delta < 0].sum() / 14.0
    if loss == 0:
        rsi = 100.0
    else:
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
    return rsi

print("orig_rsi:", timeit.timeit(orig_rsi, number=100))
print("opt_rsi:", timeit.timeit(opt_rsi, number=100))
print("orig_rsi val:", orig_rsi())
print("opt_rsi val:", opt_rsi())
