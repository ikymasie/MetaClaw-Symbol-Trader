## 2025-03-01 - Avoid Pandas df.iterrows()
**Learning:** Using `df.iterrows()` iterates row by row, boxing each row into a `Series` object which incurs a massive overhead, especially for larger dataframes.
**Action:** When iterating over a DataFrame in Pandas, replace `df.iterrows()` with `zip()` mapping the specific columns used, or `df.to_dict('records')`. The change yields dramatic speed-ups (~10x) bypassing the boxing overhead, with minimal changes to readability.
