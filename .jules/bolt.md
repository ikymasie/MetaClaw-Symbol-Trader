## 2024-05-24 - Pandas iterrows() is a massive performance bottleneck
**Learning:** Using `df.iterrows()` in Pandas creates significant overhead due to Series boxing, which can dramatically slow down data processing loops. When benchmarking, replacing `iterrows()` with `zip()` yielded more than a 25x speedup for simple dictionary creation in `y_finance.py`.
**Action:** Always replace `df.iterrows()` with `zip()`-based iteration over dataframe columns, list comprehensions, or `df.to_dict('records')` when processing market data arrays or converting formats.
