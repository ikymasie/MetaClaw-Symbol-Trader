## 2024-05-24 - Pandas iterrows() is a significant bottleneck
**Learning:** Iterating through Pandas DataFrames using `df.iterrows()` boxes each row into a Pandas Series, causing massive overhead (often 8x slower or more).
**Action:** Use `zip()` for vector-like iteration over multiple columns or `df.to_dict('records')` when dictionary access is required.
