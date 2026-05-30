import pandas as pd
import time
import numpy as np

# Create dummy data
df = pd.DataFrame({
    'time': pd.date_range('2023-01-01', periods=10000, freq='1min'),
    'open': np.random.rand(10000) * 100,
    'high': np.random.rand(10000) * 100,
    'low': np.random.rand(10000) * 100,
    'close': np.random.rand(10000) * 100,
    'volume': np.random.rand(10000) * 1000,
    'upper_bb': np.random.rand(10000) * 100,
    'sma': np.random.rand(10000) * 100,
    'lower_bb': np.random.rand(10000) * 100,
})

def using_iterrows():
    price_data = []
    for _, row in df.iterrows():
        ts = row["time"].isoformat() if hasattr(row["time"], "isoformat") else str(row["time"])
        price_data.append({
            "time": ts,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        })

def using_zip():
    price_data = []
    for ts, o, h, l, c in zip(df['time'], df['open'], df['high'], df['low'], df['close']):
        ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        price_data.append({
            "time": ts_str,
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
        })

start1 = time.time()
using_iterrows()
end1 = time.time()

start2 = time.time()
using_zip()
end2 = time.time()

iter_time = end1 - start1
zip_time = end2 - start2

print(f"iterrows: {iter_time} seconds")
print(f"zip: {zip_time} seconds")
print(f"Speedup: {iter_time / zip_time:.2f}x")
