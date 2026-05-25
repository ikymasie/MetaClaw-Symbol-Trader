## 2025-05-24 - Pandas Series Boxing Overhead in Realtime Streams
**Learning:** Using `df.iterrows()` to convert OHLCV data streams to Python dictionaries causes massive performance degradation (>10x slower) due to Pandas Series boxing/unboxing overhead for every row.
**Action:** Always use vectorized operations, `zip()` with column arrays (e.g., `zip(df['time'], df['open'])`), or `df.to_dict('records')` when translating DataFrame rows into Python dicts for JSON serialization or frontend distribution.
