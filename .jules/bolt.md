## 2025-02-27 - [TradingChart deduplication bottleneck]
**Learning:** O(N^2) `.filter` with `findIndex` used multiple times for large financial data sets (`bollingerData` and `priceData`) causes significant UI blocking overhead. `filter(m => uniquePriceData.some(p => p.time === m.time))` is also O(N*M) which could be improved with Set lookups.
**Action:** When filtering array uniqueness, especially timeseries data, use a single pass with `Set` rather than `.filter(findIndex)`.

## 2025-02-27 - [Pandas iteration and apply bottlenecks]
**Learning:** Iterative modifications with `rolling` and `iloc` combined in python for loops (`confluence.py`) causes immense overhead because Pandas series are boxed and unboxed.
**Action:** When looping over series for mathematical calculations (like Wilder smoothing), convert entirely to Numpy arrays first (`.values`) to get raw C performance.
