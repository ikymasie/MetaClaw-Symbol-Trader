## 2024-05-18 - [Avoid df.iterrows() for DataFrame iteration]
**Learning:** Iterating over Pandas DataFrames using `df.iterrows()` introduces significant overhead due to Pandas Series boxing.
**Action:** Use `zip()`-based iteration or `df.to_dict('records')` to bypass the boxing overhead and significantly speed up data transformations.
