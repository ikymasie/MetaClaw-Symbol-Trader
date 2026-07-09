## 2024-06-11 - iterrows() Performance Overhead
**Learning:** `df.iterrows()` in Pandas introduces significant performance bottlenecks due to Series boxing overhead. Using `zip()` on individual columns (e.g., `zip(df['time'], df['open'])`) or `df.to_dict('records')` can bypass this and yield ~10x speedups.
**Action:** When iterating over Pandas DataFrames is absolutely necessary, avoid `iterrows()`. Prefer vectorized operations first. If iteration is required for building a list of dictionaries, use `zip()` or `to_dict('records')`.
