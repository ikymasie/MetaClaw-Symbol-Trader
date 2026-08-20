## 2024-05-19 - Pandas Iteration Overhead
**Learning:** `df.iterrows()` in `backend/main.py`'s `get_market_data` endpoint causes significant overhead by boxing every row into a Pandas Series, creating O(N) object instantiations which slows down live data streaming.
**Action:** Replace `df.iterrows()` with vectorized approaches or `zip()`-based list comprehensions (e.g., `zip(df['time'], df['open'])`) when formatting DataFrames for JSON serialization.
