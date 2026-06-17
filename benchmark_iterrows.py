import pandas as pd
import numpy as np
import time

# Create a sample DataFrame
np.random.seed(42)
n = 10000
df = pd.DataFrame({
    'open': np.random.rand(n),
    'high': np.random.rand(n),
    'low': np.random.rand(n),
    'close': np.random.rand(n),
    'volume': np.random.rand(n),
}, index=pd.date_range('2023-01-01', periods=n, freq='1min'))

start = time.perf_counter()
bars_tf = []
for ts, row in df.iterrows():
    bars_tf.append({
        "t": ts.isoformat(),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"])
    })
t1 = time.perf_counter() - start

start = time.perf_counter()
bars_tf2 = [
    {
        "t": ts.isoformat(),
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
        "volume": float(v)
    }
    for ts, o, h, l, c, v in zip(df.index, df['open'], df['high'], df['low'], df['close'], df['volume'])
]
t2 = time.perf_counter() - start

print(f"iterrows: {t1:.4f}s")
print(f"zip: {t2:.4f}s")
print(f"Speedup: {t1/t2:.2f}x")
print(f"Results match: {bars_tf == bars_tf2}")
