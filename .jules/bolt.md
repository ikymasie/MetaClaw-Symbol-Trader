## 2024-05-24 - Avoiding Pandas df.iterrows()
**Learning:** `df.iterrows()` has severe performance overhead due to Pandas Series boxing. Simple operations can be up to 20x slower.
**Action:** When iterating over Pandas DataFrames is absolutely necessary, avoid `iterrows()`. Instead, use `zip(df['col1'], df['col2'])` to iterate over columns simultaneously, or `df.to_dict('records')` when dictionary access semantics are preferred. This dramatically improves performance in hot paths like formatting TV chart data or aggregating market data bars.
