## 2024-06-06 - [Pandas Iteration Bottlenecks]
**Learning:** `df.iterrows()` boxes each row into a pandas Series object. During tight loops, especially high-frequency financial data aggregation, this creates massive boxing overhead.
**Action:** Replace `df.iterrows()` with `zip()` over individual columns (e.g., `zip(df.index, df['open'])`) when extracting values. Alternatively, use `df.to_dict('records')` if iterating to build lists of dictionaries. This avoids Series creation entirely. Tested to yield ~25x speedups.
