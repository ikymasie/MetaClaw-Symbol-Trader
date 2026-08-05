import pandas as pd
import numpy as np

# Generate large dataframe
df = pd.DataFrame({'close': np.random.rand(100) * 100 + 50})
close = df['close']

def orig_rsi():
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = float(100 - (100 / (1 + rs)).iloc[-1]) if len(close) >= 15 else None
    return rsi

def opt_rsi():
    delta = close.diff()
    last_delta = delta.iloc[-14:]
    gain = last_delta[last_delta > 0].sum() / 14.0
    loss = -last_delta[last_delta < 0].sum() / 14.0
    if loss == 0:
        rsi = 100.0
    else:
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
    return rsi

print("orig:", orig_rsi())
print("opt:", opt_rsi())
