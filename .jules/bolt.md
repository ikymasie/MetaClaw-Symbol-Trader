## 2024-03-01 - Avoid Pandas iterrows()
**Learning:** `df.iterrows()` is a significant performance bottleneck in Pandas due to boxing each row into a Pandas Series. In data-heavy tasks like formatting price history for the frontend (`strategy.py`, `main.py`) or database prep (`market_data_aggregator.py`), it creates a major slowdown.
**Action:** Always prefer `zip()` on specific columns (e.g., `zip(df['time'], df['open'])`) or `df.to_dict('records')` (when field-to-field mapping is fine) instead of `df.iterrows()` to bypass Pandas Series boxing overhead.
