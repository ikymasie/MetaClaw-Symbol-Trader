## 2025-02-28 - Pandas iterrows Bottleneck
**Learning:** In the `get_market_data` endpoint (and potentially other places), iterating over DataFrame rows using `df.iterrows()` to convert them into dictionaries causes a significant performance bottleneck due to Pandas Series boxing overhead.
**Action:** Replace `df.iterrows()` with `zip()`-based iteration over individual columns when converting DataFrames to dictionaries. This bypasses the boxing overhead and provides approximately a 10x speedup for formatting large time-series datasets.
