## 2025-02-12 - Pandas iterrows() Boxing Overhead

**Learning:** Iterating over rows using `df.iterrows()` in Pandas is a massive performance bottleneck because it boxes each row into a Pandas `Series` object. This was found across multiple files (`main.py`, `market_data_aggregator.py`, `strategy.py`, `y_finance.py`) when building dictionaries for JSON responses or data processing.

**Action:** Always replace `df.iterrows()` with `zip()` over the individual dataframe columns or index (`zip(df.index, df["open"], df["close"])`). It directly iterates over the underlying numpy arrays, offering a >10x speedup. Remember to retain explicit `float()` casting to ensure outputs remain JSON-serializable, as numpy floats can break standard JSON encoders.
