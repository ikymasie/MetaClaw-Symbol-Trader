
## $(date +%Y-%m-%d) - Pandas iterrows() bottleneck
**Learning:** `DataFrame.iterrows()` is extremely slow because it creates a new Pandas Series object for every single row. Using `zip()` over columns or `to_dict('records')` avoids this overhead.
**Action:** Always replace `df.iterrows()` with `zip()` or `to_dict('records')` when processing dataframes in loops. When using `zip()`, retain explicit `float()` casting to ensure JSON serializability.
