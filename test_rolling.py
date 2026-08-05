import pandas as pd
import numpy as np

df = pd.DataFrame({'close': np.random.rand(100) * 100 + 50})
log_returns = np.log(df["close"] / df["close"].shift(1)).dropna()

window = 20
std1 = float(log_returns.rolling(window).std().iloc[-1])
std2 = float(log_returns.iloc[-window:].std())

print(f"std1: {std1}")
print(f"std2: {std2}")
print(f"Match: {np.isclose(std1, std2)}")
