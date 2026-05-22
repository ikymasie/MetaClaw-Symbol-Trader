## 2024-05-24 - Pandas iterrows Performance Bottleneck
**Learning:** `df.iterrows()` is an anti-pattern in Pandas as it creates a Pandas Series for each row, causing significant boxing overhead which slows down data processing loops.
**Action:** Replace `df.iterrows()` with `zip()`-based loops (e.g., `zip(df['time'], df['open'])`) or vectorization to avoid boxing overhead.
