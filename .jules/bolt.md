## 2025-03-09 - Avoid df.iterrows() in Pandas workflows
**Learning:** `df.iterrows()` boxes each row into a Pandas Series, causing massive performance bottlenecks (often 10x slower) inside loops.
**Action:** Replace `df.iterrows()` with `zip()` over columns (e.g., `zip(df['time'], df['open'])`) or `df.to_dict('records')` whenever iterating through DataFrames to eliminate boxing overhead.
