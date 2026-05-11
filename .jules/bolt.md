## 2024-05-11 - Pandas iterrows() performance bottleneck
**Learning:** `df.iterrows()` has significant overhead due to Pandas Series boxing. It iterates row by row, converting each row into a Series object, which causes performance degradation on large dataframes.
**Action:** Use `zip()` with columns (e.g., `zip(df.index, df['open'], df['high'], ...)`) or vectorized operations instead to bypass the boxing overhead and drastically improve iteration speed.
