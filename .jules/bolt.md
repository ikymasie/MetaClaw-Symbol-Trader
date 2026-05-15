## 2024-11-20 - [Pandas iterrows Performance Bottleneck]
**Learning:** `df.iterrows()` is a significant performance bottleneck in Pandas due to the overhead of boxing each row into a Series object.
**Action:** When iterating over DataFrames, consistently use `zip()` with specific columns (e.g., `zip(df['col1'], df['col2'])`) or `df.to_dict('records')` to avoid this overhead, especially in critical trading and aggregation loops.
