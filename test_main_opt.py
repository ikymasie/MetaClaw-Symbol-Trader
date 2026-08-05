import pandas as pd
import numpy as np
import timeit

df = pd.DataFrame({
    'time': pd.date_range('2023-01-01', periods=120, freq='min'),
    'open': np.random.rand(120),
    'high': np.random.rand(120),
    'low': np.random.rand(120),
    'close': np.random.rand(120),
    'upper_bb': np.random.rand(120),
    'sma': np.random.rand(120),
    'lower_bb': np.random.rand(120),
})

def orig():
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
    return price_data, bollinger

def opt():
    # Vectorized conversion using zip
    times = [ts.isoformat() if hasattr(ts, "isoformat") else str(ts) for ts in df["time"]]

    price_data = [
        {
            "time": t,
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c)
        }
        for t, o, h, l, c in zip(times, df["open"], df["high"], df["low"], df["close"])
    ]

    bollinger = [
        {
            "time": t,
            "upper": float(u),
            "middle": float(m),
            "lower": float(lo)
        }
        for t, u, m, lo in zip(times, df["upper_bb"], df["sma"], df["lower_bb"])
    ]

    return price_data, bollinger


def opt2():
    # to_dict records
    return None

print("orig:", timeit.timeit(orig, number=100))
print("opt:", timeit.timeit(opt, number=100))
