## 2024-05-18 - [Pandas Iteration Bottleneck]
**Learning:** Using `df.iterrows()` to parse Pandas DataFrames into dictionaries (e.g., for JSON serialization to the frontend or database inserts) introduces massive boxing/unboxing overhead, slowing down time-series data parsing by up to 10x.
**Action:** Always prefer vectorized operations or Python's native `zip()` with list/dict comprehensions (e.g., `zip(df['time'], df['close'])`) over `df.iterrows()` when converting OHLCV DataFrames to native Python structures.
