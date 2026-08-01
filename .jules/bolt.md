## 2024-05-19 - Frontend Fleet View Deduplication Bottleneck
**Learning:** Found multiple O(N) array `.filter()` passes resolving identical datasets directly in the render lifecycle of `frontend/src/app/fleet/page.tsx` when grouping running/stopped/filtered bot lists. This causes unnecessary array allocations and full N passes.
**Action:** Replace multiple separate `.filter()` array passes with a single `.reduce()` step wrapped in `useMemo` to construct both counts and filtered elements in O(N) time and strictly bound recalculations to dependency changes.
