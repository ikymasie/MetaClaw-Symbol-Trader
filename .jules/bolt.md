## 2025-03-08 - [Pandas iterrows() anti-pattern]
**Learning:** `df.iterrows()` is extremely slow in Pandas due to Series boxing overhead for every row yielded. In testing, `zip()` on columns is ~50x faster and `df.to_dict('records')` is ~10x faster.
**Action:** Always prefer vectorized operations first. If row-by-row iteration is strictly necessary, use `zip()` for specific columns or `df.to_dict('records')` when the entire row is needed as a dictionary. Never use `df.iterrows()`.
