## 2024-06-10 - Pandas Iterrows Performance
**Learning:** `df.iterrows()` is extremely slow for building dictionaries or lists of dictionaries out of a DataFrame. Replacing it with `zip()` on individual columns or `df.to_dict('records')` offers massive performance improvements (10x-20x faster). The `zip()` method is faster but `to_dict('records')` or directly vectorized ops with list comprehension on zip are also very fast.
**Action:** Replace `df.iterrows()` loops with `zip()` based iterations or `to_dict('records')` when constructing JSON-like responses from pandas DataFrames.
