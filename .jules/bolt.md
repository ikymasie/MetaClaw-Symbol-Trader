## 2024-05-18 - [Optimizing Nested Array Searches in React Renders]
**Learning:** Found a sneaky O(N*M) bottleneck in `TradingChart.tsx` where `.filter()` iterated over markers while internally using `.some()` to check against the entire price data array on every render cycle. This blocked the main thread significantly for large datasets.
**Action:** Always convert the lookup array into a `Set` before filtering to transform O(N*M) time complexity into O(N+M) with O(1) lookups.
