## 2024-10-03 - O(N^2) Bottlenecks in Chart Rendering
**Learning:** The `TradingChart.tsx` component processes array data frequently using `.map().filter()` chains that internally call `.findIndex()` for deduplication. This causes severe UI blocking due to O(N^2) or even O(3*N^2) complexity on large datasets.
**Action:** Always replace `.map().filter((_, i, self) => i === self.findIndex(...))` with a single `for...of` pass using a `Set` to track seen values, reducing complexity to O(N).
