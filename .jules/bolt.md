## 2024-06-04 - Pandas Performance Bottleneck
**Learning:** Found significant performance overhead in Pandas loops using `df.iterrows()`. This anti-pattern creates a new Pandas Series object for each row (boxing overhead), which is extremely slow, especially during real-time data processing and backtesting.
**Action:** Always prefer vectorized operations where possible. If iteration is necessary, use `zip()` or `df.to_dict('records')` to avoid creating Pandas Series objects entirely. Example: `zip(df['time'], df['open'])`.
