## 2024-05-13 - Pandas `.iterrows()` Performance Bottleneck
**Learning:** Using `df.iterrows()` to convert Pandas DataFrames into lists of dictionaries or process rows individually is a severe performance anti-pattern due to Pandas Series boxing overhead.
**Action:** Always replace `.iterrows()` loops with vectorized operations, `zip()`-based list comprehensions over columns (e.g., `zip(df['time'], df['close'])`), or `df.to_dict('records')` to achieve massive speedups without altering logical behavior.
