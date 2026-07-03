## $(date +%Y-%m-%d) - Pandas iterrows() bottleneck
**Learning:** `df.iterrows()` is notoriously slow because it boxes each row into a new Pandas Series object, adding massive overhead during iteration loops.
**Action:** Replace `iterrows()` loops with `zip()`-based list comprehensions accessing specific columns directly (e.g. `zip(df['colA'], df['colB'])`) or `df.to_dict('records')`. This provides a significant speedup (~10x) without sacrificing readability.
