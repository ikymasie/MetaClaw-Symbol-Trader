## 2024-05-24 - [Avoid df.iterrows() for Object Conversion]
**Learning:** `df.iterrows()` is known to be slow due to Pandas Series boxing overhead. Using `zip()` on individual columns (or `itertuples()`) is significantly faster when converting Pandas DataFrames to native Python dictionaries or objects, achieving up to 10x performance gains.
**Action:** When mapping a DataFrame into a list of dictionaries for JSON serialization or Firestore storage, replace `df.iterrows()` loops with `zip(df.index, df['col1'], ...)` comprehensions or `df.to_dict('records')`.
