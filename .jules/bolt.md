## 2024-05-01 - [O(N^2) Array Deduplication in React]
**Learning:** Found an $O(N^2)$ bottleneck inside `frontend/src/components/dashboard/TradingChart.tsx` where `.filter((val, idx, self) => idx === self.findIndex((t) => t.time === val.time))` was used for data deduplication.
**Action:** Replace `findIndex` within `.filter()` or `.map()` with a `Set` for O(1) membership checks, reducing the time complexity to $O(N)$ for array deduplication. Also, collapse multiple `.map().filter()` chains over the same array into a single `for...of` pass when building multiple target arrays.
