import pandas as pd
import numpy as np
import time

def test_iterrows():
    df = pd.DataFrame({
        "time": pd.date_range("2023-01-01", periods=10000, freq="min"),
        "open": np.random.rand(10000),
        "high": np.random.rand(10000),
        "low": np.random.rand(10000),
        "close": np.random.rand(10000),
        "upper_bb": np.random.rand(10000),
        "sma": np.random.rand(10000),
        "lower_bb": np.random.rand(10000),
    })

    start = time.time()
    price_data = []
    bollinger = []
    for _, row in df.iterrows():
        ts = row["time"].isoformat() if hasattr(row["time"], "isoformat") else str(row["time"])
        price_data.append({
            "time": ts,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        })
        bollinger.append({
            "time": ts,
            "upper": float(row["upper_bb"]),
            "middle": float(row["sma"]),
            "lower": float(row["lower_bb"]),
        })
    return time.time() - start

def test_zip():
    df = pd.DataFrame({
        "time": pd.date_range("2023-01-01", periods=10000, freq="min"),
        "open": np.random.rand(10000),
        "high": np.random.rand(10000),
        "low": np.random.rand(10000),
        "close": np.random.rand(10000),
        "upper_bb": np.random.rand(10000),
        "sma": np.random.rand(10000),
        "lower_bb": np.random.rand(10000),
    })

    start = time.time()
    price_data = []
    bollinger = []
    for t, o, h, l, c, upper, sma, lower in zip(df["time"], df["open"], df["high"], df["low"], df["close"], df["upper_bb"], df["sma"], df["lower_bb"]):
        ts = t.isoformat() if hasattr(t, "isoformat") else str(t)
        price_data.append({
            "time": ts,
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
        })
        bollinger.append({
            "time": ts,
            "upper": float(upper),
            "middle": float(sma),
            "lower": float(lower),
        })
    return time.time() - start

print(f"iterrows: {test_iterrows():.4f}s")
print(f"zip: {test_zip():.4f}s")
