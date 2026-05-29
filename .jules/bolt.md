## 2024-05-24 - Pandas iterrows() bottleneck in list-of-dict conversions
**Learning:** `df.iterrows()` has severe performance bottlenecks due to Pandas Series boxing overhead when iterating row-by-row. In our tests, `zip()` is over 10x faster for converting DataFrame rows into a list of dictionaries.
**Action:** Never use `df.iterrows()` when iterating through large dataframes to create lists or dictionaries. Prefer `zip()`-based list comprehensions (e.g. `zip(df['time'], df['open'])`) to directly access underlying column arrays and bypass boxing overhead.
