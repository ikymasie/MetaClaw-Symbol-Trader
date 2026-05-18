## 2024-05-15 - Pandas iterrows Bottleneck
**Learning:** The codebase heavily uses Pandas DataFrames, and traversing them with `df.iterrows()` causes massive performance bottlenecks due to row Series boxing overhead.
**Action:** Always prefer `zip()` on specific columns or `df.to_dict('records')` when processing Pandas rows manually to avoid overhead.
