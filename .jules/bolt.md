## 2026-07-27 - [O(N) Optimization vs. useMemo]
**Learning:** While combining multiple `.filter()` passes into a single `.reduce()` improves big-O from O(3N) to O(N), wrapping it in `useMemo` yields far greater performance wins by avoiding the computation altogether when dependencies haven't changed. Also, avoid committing dynamically generated lockfiles like `pnpm-lock.yaml` when making routine code optimizations to keep PR diffs clean.
**Action:** When implementing O(N) deduplication or aggregation on props, always wrap in `useMemo` and verify lockfiles aren't staged inadvertently.
