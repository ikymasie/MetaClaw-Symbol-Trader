## 2025-05-30 - [Optimize Array Filtering in React Renders]
**Learning:** Found multiple instances where UI components calculated stats (like `runningCount` and `stoppedCount`) by iterating over the same list (`bots.filter()`) multiple times per render cycle. This is an O(K * N) anti-pattern.
**Action:** Replace multiple `.filter()` passes on the same array with a single `.reduce()` or `for` loop pass to extract multiple lists and aggregates at once. Always wrap these aggregations in `useMemo` so that the O(N) cost is only paid when the underlying data changes, not on every re-render.
