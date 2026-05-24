import pandas as pd
import time
import numpy as np

# Generate sample data
N = 10000
df = pd.DataFrame({
    'time': pd.date_range(start='1/1/2020', periods=N, freq='1min'),
    'open': np.random.rand(N),
    'high': np.random.rand(N),
    'low': np.random.rand(N),
    'close': np.random.rand(N),
    'volume': np.random.rand(N),
    'upper_bb': np.random.rand(N),
    'sma': np.random.rand(N),
    'lower_bb': np.random.rand(N),
})

# iterrows
start = time.time()
res1 = []
for _, row in df.iterrows():
    res1.append({
        "time": row["time"].isoformat() if hasattr(row["time"], "isoformat") else str(row["time"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
    })
print(f"iterrows: {time.time() - start:.4f}s")

# itertuples
start = time.time()
res2 = []
for row in df.itertuples(index=False):
    res2.append({
        "time": row.time.isoformat() if hasattr(row.time, "isoformat") else str(row.time),
        "open": float(row.open),
        "high": float(row.high),
        "low": float(row.low),
        "close": float(row.close),
    })
print(f"itertuples: {time.time() - start:.4f}s")

# zip
start = time.time()
res3 = []
for t, o, h, l, c in zip(df['time'], df['open'], df['high'], df['low'], df['close']):
    res3.append({
        "time": t.isoformat() if hasattr(t, "isoformat") else str(t),
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
    })
print(f"zip: {time.time() - start:.4f}s")
