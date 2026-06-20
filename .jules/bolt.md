## 2023-10-27 - [Pandas Iterrows Bottleneck]
**Learning:** `df.iterrows()` is a known performance anti-pattern in Pandas because it returns each row as a `pd.Series`, incurring significant boxing overhead. In this codebase, it was used repeatedly for serializing data into dicts or frontend charts.
**Action:** Replace `df.iterrows()` with `zip()` over specific columns (e.g. `zip(df['time'], df['open'])`) or `df.to_dict('records')` when processing Pandas DataFrames sequentially to drastically improve iteration speed.
