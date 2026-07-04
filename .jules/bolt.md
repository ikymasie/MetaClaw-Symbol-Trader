## 2024-07-04 - df.iterrows() Performance Bottleneck
**Learning:** Using df.iterrows() in Pandas operations introduces significant performance bottlenecks due to Pandas Series boxing overhead.
**Action:** Prefer vectorized operations, zip()-based list comprehensions, or df.to_dict('records') to bypass this overhead, which can yield up to a ~10x speedup.
