## 2024-05-18 - Replacing iterrows with zip for 10x loop speedup
**Learning:** `df.iterrows()` is highly unoptimized because it boxes each row into a Series object. This is a common performance trap in pandas. Bypassing it by using `zip()` over the individual columns (or using `df.to_dict('records')` when the columns are very wide) results in a measurable 10x to 15x speedup.
**Action:** Always check for `df.iterrows()` loops and refactor them using `zip()` or native dictionary conversions where appropriate.
