import pandas as pd
import numpy as np
import time

n = 10000
df = pd.DataFrame({
    'time': pd.date_range(start='1/1/2020', periods=n),
    'open': np.random.randn(n),
    'high': np.random.randn(n),
    'low': np.random.randn(n),
    'close': np.random.randn(n),
})

start = time.time()
res1 = []
for _, row in df.iterrows():
    res1.append({
        'time': row['time'].isoformat(),
        'open': float(row['open']),
        'close': float(row['close']),
    })
print(f"iterrows: {time.time() - start:.4f}s")

start = time.time()
res2 = []
for t, o, c in zip(df['time'], df['open'], df['close']):
    res2.append({
        'time': t.isoformat(),
        'open': float(o),
        'close': float(c),
    })
print(f"zip: {time.time() - start:.4f}s")
