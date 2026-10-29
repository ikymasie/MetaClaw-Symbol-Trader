## 2026-10-29 - Pandas .iloc in loops
**Learning:** Using `.iloc` inside a Python `for` loop to access Pandas Series values creates a massive performance bottleneck due to boxing and unboxing overhead for every single access.
**Action:** Always extract the raw numpy array using `.values` before the loop (e.g. `highs_vals = highs.values`) and index into the numpy array directly for O(1) performance.
