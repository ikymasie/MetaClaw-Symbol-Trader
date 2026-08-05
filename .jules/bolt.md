## 2024-05-24 - Pandas `rolling().iloc[-1]` Overhead
**Learning:** Calculating rolling statistics (like `.rolling(20).mean()`) on an entire DataFrame just to extract the final value (`.iloc[-1]`) causes significant O(N) overhead in Python/Pandas when N is large. It recalculates the rolling mean for all rows.
**Action:** Replace `df.rolling(window).mean().iloc[-1]` with `df.iloc[-window:].mean()`. This O(1) slice approach provides >40x speedups for single-value extractions.
