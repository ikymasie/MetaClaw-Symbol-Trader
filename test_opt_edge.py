import pandas as pd
import numpy as np

def test_rsi(size):
    df = pd.DataFrame({'close': np.random.rand(size) * 100 + 50})
    close = df['close']

    # Original
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    orig_rsi = float(100 - (100 / (1 + rs)).iloc[-1]) if len(close) >= 15 else None

    # Opt
    if len(close) >= 15:
        last_delta = delta.iloc[-14:]
        gain_opt = last_delta[last_delta > 0].sum() / 14.0
        loss_opt = -last_delta[last_delta < 0].sum() / 14.0
        if loss_opt == 0:
            opt_rsi = 100.0
        else:
            rs_opt = gain_opt / loss_opt
            opt_rsi = 100 - (100 / (1 + rs_opt))
    else:
        opt_rsi = None

    print(f"Size: {size}, Orig: {orig_rsi}, Opt: {opt_rsi}")

test_rsi(14)
test_rsi(15)
test_rsi(50)
