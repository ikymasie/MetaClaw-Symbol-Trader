import pandas as pd
import numpy as np
import timeit

df = pd.DataFrame({'close': np.random.rand(100000) * 100 + 50})
close = df['close']

def orig_ma():
    return float(close.rolling(20).mean().iloc[-1])

def opt_ma():
    return float(close.iloc[-20:].mean())

print("orig_ma:", timeit.timeit(orig_ma, number=100))
print("opt_ma:", timeit.timeit(opt_ma, number=100))
