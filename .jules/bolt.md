## 2024-06-25 - Pandas iteration performance bottleneck
**Learning:** `df.iterrows()` in Pandas is a massive performance bottleneck due to Series boxing overhead. In our test with 10k rows it took ~0.60s while a `zip()` approach took ~0.06s (10x faster).
**Action:** Use `zip(df['col1'], df['col2'])` or `df.to_dict('records')` instead of `df.iterrows()`. Avoid modifying existing loop behavior. Add inline performance comments.
