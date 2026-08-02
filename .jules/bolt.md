## 2024-05-24 - Numpy fmax vs maximum for Pandas compatibility
**Learning:** When replacing Pandas aggregation functions like `.max(axis=1)` with NumPy array operations for performance, using `np.maximum()` can cause functional regressions if the data contains NaNs (e.g., from `df.shift(1)`). Pandas ignores NaNs by default (`skipna=True`), but `np.maximum()` propagates them.
**Action:** Use `np.fmax()` instead of `np.maximum()` when optimizing Pandas logic with NumPy to safely ignore NaNs and maintain strict functional equivalence.
