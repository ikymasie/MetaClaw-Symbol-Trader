import pandas as pd
import numpy as np
import time

# Create dummy data
N = 10000
df = pd.DataFrame({
    'time': pd.date_range(start='1/1/2020', periods=N, freq='min'),
    'open': np.random.randn(N),
    'high': np.random.randn(N),
    'low': np.random.randn(N),
    'close': np.random.randn(N),
    'upper_bb': np.random.randn(N),
    'sma': np.random.randn(N),
    'lower_bb': np.random.randn(N)
})

# iterrows approach
start = time.time()
price_data1 = []
bollinger1 = []
for _, row in df.iterrows():
    ts = row["time"].isoformat() if hasattr(row["time"], "isoformat") else str(row["time"])
    price_data1.append({
        "time": ts,
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
    })
    bollinger1.append({
        "time": ts,
        "upper": float(row["upper_bb"]),
        "middle": float(row["sma"]),
        "lower": float(row["lower_bb"]),
    })
time_iterrows = time.time() - start

# zip approach
start = time.time()
price_data2 = []
bollinger2 = []
for t, o, h, l, c, upper, mid, lower in zip(
    df["time"], df["open"], df["high"], df["low"], df["close"], df["upper_bb"], df["sma"], df["lower_bb"]
):
    ts = t.isoformat() if hasattr(t, "isoformat") else str(t)
    price_data2.append({
        "time": ts,
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
    })
    bollinger2.append({
        "time": ts,
        "upper": float(upper),
        "middle": float(mid),
        "lower": float(lower),
    })
time_zip = time.time() - start

print(f"iterrows time: {time_iterrows:.4f}s")
print(f"zip time: {time_zip:.4f}s")
print(f"Speedup: {time_iterrows / time_zip:.2f}x")
