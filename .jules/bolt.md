## 2024-05-30 - [Performance] O(N^2) Anti-pattern in Array Filtering
**Learning:** Found an O(N^2) performance bottleneck in `TradingChart.tsx` where `array.filter` was combined with `array.findIndex` to deduplicate items. This is particularly harmful for continuous live data feeds (like websocket tick data) where array sizes grow rapidly.
**Action:** When deduplicating arrays in React components, especially for high-frequency data (like charting or terminal feeds), always use a `Set` to track seen items for O(N) deduplication rather than nested array iterations like `findIndex` or `some`.
