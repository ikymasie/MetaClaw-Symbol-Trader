## 2024-05-15 - [Pandas Iteration Bottleneck]
**Learning:** `df.iterrows()` creates significant performance bottlenecks due to Pandas Series boxing overhead. Using `zip()`-based list comprehensions over columns or `itertuples()`/`to_dict('records')` avoids this overhead and processes rows substantially faster.
**Action:** Replace `iterrows()` with `zip()` list comprehensions (e.g., `zip(df['time'], df['open'])`) or vectorized operations in performance-sensitive loops.
