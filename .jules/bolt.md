## 2024-03-24 - Pandas DataFrame Max Overhead
**Learning:** Using `pd.concat([a, b, c], axis=1).max(axis=1)` is a massive bottleneck in pandas because it instantiates a new DataFrame just to compute the row-wise max.
**Action:** Use nested `np.fmax(a, np.fmax(b, c))` for vectorized row-wise maximum calculations without DataFrame instantiation overhead.
