## 2024-05-20 - [Pandas iterrows() bottleneck]
**Learning:** `df.iterrows()` is extremely slow because it boxes each row into a Pandas Series, causing significant overhead in hot loops.
**Action:** Use `zip()` or `df.to_dict('records')` when extracting values from multiple columns to bypass Pandas Series boxing overhead. Using `zip()` can yield up to a >25x speedup.
