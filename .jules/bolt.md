## 2026-08-03 - Pandas max(axis=1) Instantiation Overhead
**Learning:** In Pandas, calculating row-wise maximums across multiple Series using `pd.concat([s1, s2, s3], axis=1).max(axis=1)` incurs extremely high overhead due to intermediate DataFrame instantiation and index alignment.
**Action:** Use nested `np.fmax(a, np.fmax(b, c))` instead. It operates directly on the underlying arrays for vectorized C-level performance while correctly handling NaNs, mirroring Pandas' behavior without the instantiation cost.
