import pandas as pd
import time
import numpy as np
import datetime

# Create dummy data
n = 10000
df = pd.DataFrame({
    'time': [datetime.datetime.now() for _ in range(n)],
    'open': np.random.rand(n),
    'high': np.random.rand(n),
    'low': np.random.rand(n),
    'close': np.random.rand(n),
    'volume': np.random.rand(n),
    'sma': np.random.rand(n),
    'upper_bb': np.random.rand(n),
    'lower_bb': np.random.rand(n),
})

# Test iterrows
start = time.perf_counter()
res_iterrows = []
for _, row in df.iterrows():
    res_iterrows.append({
        "time": str(row["time"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
    })
time_iterrows = time.perf_counter() - start

# Test zip
start = time.perf_counter()
res_zip = []
for t, o, h, l, c in zip(df['time'], df['open'], df['high'], df['low'], df['close']):
    res_zip.append({
        "time": str(t),
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
    })
time_zip = time.perf_counter() - start

# Test to_dict
start = time.perf_counter()
# res_dict = df[['time', 'open', 'high', 'low', 'close']].to_dict('records') # Needs time to str
# List comp with to_dict
res_dict = [{
    "time": str(r["time"]),
    "open": float(r["open"]),
    "high": float(r["high"]),
    "low": float(r["low"]),
    "close": float(r["close"])
} for r in df[['time', 'open', 'high', 'low', 'close']].to_dict('records')]
time_dict = time.perf_counter() - start

print(f"Iterrows: {time_iterrows:.5f}s")
print(f"Zip:      {time_zip:.5f}s")
print(f"To dict:  {time_dict:.5f}s")
print(f"Zip is {time_iterrows/time_zip:.1f}x faster")
