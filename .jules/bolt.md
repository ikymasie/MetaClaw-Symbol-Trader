## 2024-06-05 - [Pandas iterrows() boxing overhead]
**Learning:** Pandas `df.iterrows()` iterates over rows as Series objects, which introduces significant "boxing" overhead. This bottleneck is highly noticeable inside real-time loops that parse or format large dataframes for WebSockets and APIs.
**Action:** Replace `df.iterrows()` by iterating directly with `zip(df['col1'], df['col2'])` when multiple columns are required, or use `df.to_dict('records')` when processing data directly into lists of dictionaries, which sidesteps Pandas Series entirely.
