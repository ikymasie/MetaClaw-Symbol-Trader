## 2025-08-25 - O(N^2) Deduplication Bottleneck in Dashboard Charts
**Learning:** In highly interactive React components dealing with large real-time arrays (like TradingChart.tsx processing lightweight-charts data), using .filter() with .findIndex() to deduplicate by time inherently scales as O(N^2). This creates significant main thread blocking as datasets grow over time.
**Action:** Always replace .findIndex() within iterative array methods with an O(N) Set-based tracking approach to ensure components scale smoothly as stream sizes increase.
