## 2024-06-03 - [Pandas iterrows Performance]
**Learning:** Pandas `df.iterrows()` creates a new Series object for each row, adding significant boxing overhead which slows down iterations by orders of magnitude compared to `zip()` or vectorization.
**Action:** Replace `df.iterrows()` with `zip()`-based iteration for generating dicts/lists when processing Pandas DataFrames.
