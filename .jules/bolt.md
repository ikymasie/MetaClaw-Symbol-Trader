## 2024-05-19 - O(N^2) Bottlenecks in React Rendering
**Learning:** Using `findIndex()` inside `.filter()` or `.map()` (like `arr.filter((v, i, s) => i === s.findIndex(t => t.time === v.time))`) to deduplicate arrays creates a hidden O(N^2) performance bottleneck. When run on every render or data update (like streaming chart data), it can severely degrade UI responsiveness.
**Action:** Always replace nested O(N) operations like `findIndex` during array iterations with O(N) structures like a `Set` or `Map` to track seen values.
