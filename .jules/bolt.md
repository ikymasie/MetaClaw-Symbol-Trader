## 2024-05-24 - Pandas iterrows Bottleneck
**Learning:** `df.iterrows()` in Pandas operations creates a significant bottleneck due to Series boxing overhead for every row, especially when building large JSON-serializable dictionaries for API responses.
**Action:** Replace `df.iterrows()` with `zip(df['col1'], df['col2'], ...)` loops for faster OHLC processing and data transformation.
