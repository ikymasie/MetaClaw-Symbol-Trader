## 2025-02-20 - [Pandas Iteration Overhead]
**Learning:** `df.iterrows()` has severe performance penalties in tight loops or data transformation tasks due to Pandas Series boxing for every row (type casting overhead).
**Action:** Always prefer `zip()` for simple columnar iteration or `df.to_dict('records')` when dictionary access (`row["key"]` or `row.get("key")`) is required. This avoids type inference overhead on each loop iteration and speeds up serialization/processing by 10x+.
