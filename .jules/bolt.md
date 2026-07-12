## 2024-07-12 - Replacing Pandas iterrows() with zip()
**Learning:** Using df.iterrows() incurs high overhead due to Pandas Series boxing. Replacing it with zip() list comprehension directly reading columns provides a substantial speedup.
**Action:** Always look for and replace df.iterrows() with zip() or similar vectorized alternatives when iterating through DataFrames.
