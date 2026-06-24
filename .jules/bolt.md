## 2024-05-15 - [Pandas iterrows Overhead]
**Learning:** `df.iterrows()` is a significant performance bottleneck due to Pandas Series boxing overhead. Using `zip()` on specific columns or `to_dict('records')` is significantly faster for row-wise iteration.
**Action:** Replace `df.iterrows()` with `zip()` or `to_dict('records')` wherever row-by-row iteration is necessary in Pandas.
