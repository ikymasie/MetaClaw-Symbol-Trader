## 2024-05-18 - Replacing Pandas df.iterrows() with zip()
**Learning:** Pandas `df.iterrows()` creates significant performance bottlenecks when processing OHLC financial data due to Pandas Series boxing overhead on every row. Profiling shows it takes ~10x longer than using native Python loops.
**Action:** Always prefer `zip()`-based list comprehensions (e.g., `zip(df.index, df['open'], ...)`) over `df.iterrows()` when iterating through rows of a dataframe to construct Python dictionaries or lists.
