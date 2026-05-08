import pandas as pd
import json

excel_file = '/Users/ikymasie/Documents/Work/Projects/MetaClaw-Symbol-Trader/Weltrade_Full_MT5_Symbols.xlsx'
xl = pd.ExcelFile(excel_file)

data = {}
for sheet_name in xl.sheet_names:
    df = xl.parse(sheet_name)
    print(f"\nSheet: {sheet_name}")
    for _, row in df.iterrows():
        name = str(row.get("Symbol", "")).strip()
        if not name or name == "nan":
            continue
        category = str(row.get("Category", sheet_name)).strip()
        description = str(row.get("Description", "")).strip()
        if sheet_name not in data:
            data[sheet_name] = []
        data[sheet_name].append({
            "name": name,
            "category": category,
            "description": description
        })

print(json.dumps(data, indent=2))
