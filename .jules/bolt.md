## 2024-05-18 - Avoid Pandas DataFrame.iterrows()
**Learning:** In Pandas, iterating over rows via `df.iterrows()` wraps each row into a Pandas Series, causing massive boxing/unboxing overhead. In data aggregation loops (like in `market_data_aggregator.py`), this can become a severe performance bottleneck.
**Action:** Replace `df.iterrows()` with a list comprehension that zips the underlying arrays (`zip(df.index, df["open"], df["high"], ...)`). This directly pulls values bypassing the Series construction overhead, providing ~10x speedups.
