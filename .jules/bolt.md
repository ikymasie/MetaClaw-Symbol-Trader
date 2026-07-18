## 2024-05-24 - df.iterrows() Performance Bottleneck
**Learning:** Using `df.iterrows()` for JSON response generation introduces significant Pandas Series boxing overhead.
**Action:** Replace `df.iterrows()` with `zip()`-based column iteration, retaining explicit `float()` casting to ensure JSON serializability.
