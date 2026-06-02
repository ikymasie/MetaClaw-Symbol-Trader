## 2024-06-02 - [Pandas Iteration Bottleneck]
**Learning:** Found multiple instances of `df.iterrows()` used for data transformation and API response building. `iterrows()` is extremely slow because it boxes each row into a Pandas Series. Benchmarking showed `zip()` over columns or `df.to_dict('records')` is ~10x-20x faster.
**Action:** Always replace `df.iterrows()` with `zip()` over individual columns (e.g., `zip(df['time'], df['open'])`) when extracting sequential data, or `df.to_dict('records')` when schema flexibility is needed (like reading from Excel).
