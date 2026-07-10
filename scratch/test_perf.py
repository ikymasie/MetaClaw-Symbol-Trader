import pandas as pd
import time

# Create a sample dataframe
df = pd.DataFrame({
    'time': pd.date_range(start='1/1/2021', periods=10000, freq='min'),
    'open': range(10000),
    'high': range(10000),
    'low': range(10000),
    'close': range(10000),
    'upper_bb': range(10000),
    'sma': range(10000),
    'lower_bb': range(10000)
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
print("iterrows() took:", time.time() - start)

start = time.time()
price_data2 = []
bollinger2 = []
for t, o, h, l, c, u, m, l_bb in zip(
    df["time"], df["open"], df["high"], df["low"], df["close"],
    df["upper_bb"], df["sma"], df["lower_bb"]
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
        "upper": float(u),
        "middle": float(m),
        "lower": float(l_bb),
    })
print("zip() took:", time.time() - start)

assert price_data == price_data2
assert bollinger == bollinger2
print("Outputs are identical.")
