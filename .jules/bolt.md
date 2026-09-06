## 2026-09-06 - [ExecutionerPanel Filter Collapse]
**Learning:** Multiple array `.filter().length` passes on the same prop inside a React component render function create hidden O(N) bottlenecks and redundant array allocations.
**Action:** Use a single `useMemo` wrapping a `.reduce()` loop to calculate multiple aggregate metrics simultaneously, saving renders and iteration overhead.
