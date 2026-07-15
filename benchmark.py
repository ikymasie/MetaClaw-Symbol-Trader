import pandas as pd
import numpy as np
import time

# Create a sample dataframe
N = 5000
df = pd.DataFrame({
    "time": pd.date_range(start="2021-01-01", periods=N, freq="min"),
    "open": np.random.rand(N),
    "high": np.random.rand(N),
    "low": np.random.rand(N),
    "close": np.random.rand(N),
    "upper_bb": np.random.rand(N),
    "sma": np.random.rand(N),
    "lower_bb": np.random.rand(N),
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
end = time.time()
iterrows_time = end - start

# zip approach
start = time.time()
price_data2 = []
bollinger2 = []
for t, o, h, l, c, upper, sma, lower in zip(df["time"], df["open"], df["high"], df["low"], df["close"], df["upper_bb"], df["sma"], df["lower_bb"]):
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
        "middle": float(sma),
        "lower": float(lower),
    })
end = time.time()
zip_time = end - start

print(f"iterrows: {iterrows_time:.4f}s")
print(f"zip: {zip_time:.4f}s")
print(f"Speedup: {iterrows_time/zip_time:.2f}x")
