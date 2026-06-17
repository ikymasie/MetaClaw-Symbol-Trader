import pandas as pd
from datetime import datetime

def test_zip_format():
    df = pd.DataFrame({
        "time": [datetime(2024,1,1), datetime(2024,1,2)],
        "open": [10, 20],
        "high": [12, 22],
        "low": [8, 18],
        "close": [11, 21],
        "upper_bb": [15, 25],
        "sma": [10, 20],
        "lower_bb": [5, 15]
    })

    price_data = []
    bollinger = []

    for time_val, o, h, l, c, upper, middle, lower in zip(
        df["time"], df["open"], df["high"], df["low"], df["close"],
        df["upper_bb"], df["sma"], df["lower_bb"]
    ):
        ts = time_val.isoformat() if hasattr(time_val, "isoformat") else str(time_val)
        price_data.append({
            "time": ts, "open": float(o), "high": float(h),
            "low": float(l), "close": float(c),
        })
        bollinger.append({
            "time": ts, "upper": float(upper),
            "middle": float(middle), "lower": float(lower),
        })

    assert len(price_data) == 2
    assert price_data[0]["time"] == "2024-01-01T00:00:00"
    assert price_data[0]["open"] == 10.0
    assert bollinger[0]["upper"] == 15.0
