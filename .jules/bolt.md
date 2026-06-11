## 2024-05-30 - [Pandas Iteration Bottleneck]
**Learning:** Found widespread use of `df.iterrows()` in critical market data processing loops (e.g., `backend/main.py`, `backend/market_data_aggregator.py`, `backend/strategy.py`). `iterrows()` causes significant Pandas Series boxing overhead, creating performance bottlenecks during high-frequency iteration.
**Action:** Replace `df.iterrows()` with `zip()` over dataframe columns or use `df.to_dict('records')` when constructing large lists of dictionaries. This standard Pandas optimization significantly reduces iteration time.
