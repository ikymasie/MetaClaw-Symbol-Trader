"""
MT5 Data Vendor Adapter for TradingAgents (Phase 4 §5.2)
==========================================================
Registers MetaTrader 5 as a third data vendor alongside YFinance and
Alpha Vantage.  Because the backend already has a live MT5 connection
flowing through `mt5_hub`, the research framework can now consume the
**exact same bars** that the execution engine trades on, eliminating
data-source divergence.

Each adapter function:
  * Returns data in the same shape as the yfinance / alpha_vantage functions
    it shadows, OR returns None to signal "vendor unavailable", which triggers
    the standard fallback chain in `route_to_vendor()`.
  * Uses the module-level `import MetaTrader5 as _mt5` guard — on systems
    without the MT5 terminal the adapter silently opts out.
"""

from __future__ import annotations

import logging
from typing import Optional, Any

logger = logging.getLogger("tradeclaw.mt5_vendor")

# Lazy import — MetaTrader5 is Windows-only at the C extension level.
# On macOS/Linux the import fails; the vendor adapter returns None so
# the fallback chain routes to YFinance.
try:
    import MetaTrader5 as _mt5
except Exception:
    _mt5 = None  # type: ignore


# ─────────────────────────────────────────────────────────────
# VENDOR ADAPTER FUNCTIONS
# ─────────────────────────────────────────────────────────────

def get_mt5_bars(symbol: str, start_date: str, end_date: str, **kwargs) -> Optional[Any]:
    """
    Fetch OHLCV bars from MT5 as a list-of-dicts (same shape as yfinance
    output → compatible with the pandas DataFrame consumers in TradingAgents).

    `symbol` is the clean ticker (e.g. "EURUSD") — the adapter appends the
    broker suffix internally.

    Returns None if MT5 is unavailable, allowing `route_to_vendor()` to
    fall back to the next vendor in the chain.
    """
    if _mt5 is None:
        return None

    from symbol_service import symbol_service
    broker = symbol_service.get_broker_symbol(symbol)
    if not broker:
        return None

    try:
        import pandas as pd
        from datetime import timezone as _tz

        # Parse date range — default to last 200 1h bars
        if start_date:
            try:
                start_dt = pd.Timestamp(start_date).to_pydatetime()
            except Exception:
                start_dt = None
        else:
            start_dt = None

        if start_dt:
            # Map datetime → position argument for copy_rates_from
            # We use copy_rates_from (start → count) for date-range requests.
            # MT5.count starts from 'start' backward.
            rates = _mt5.copy_rates_from(broker, _mt5.TIMEFRAME_H1, start_dt, 200)
        else:
            rates = _mt5.copy_rates_from_pos(broker, _mt5.TIMEFRAME_H1, 0, 200)

        if rates is None or len(rates) == 0:
            logger.debug(f"MT5 returned no bars for {broker}")
            return None

        # Normalise to list-of-dicts (same as yfinance output)
        bars = []
        for r in rates:
            ts = pd.to_datetime(r["time"], unit="s", utc=True).strftime("%Y-%m-%d %H:%M:%S")
            bars.append({
                "Date": ts,
                "Open":  float(r["open"]),
                "High":  float(r["high"]),
                "Low":   float(r["low"]),
                "Close": float(r["close"]),
                "Volume": float(r.get("tick_volume", r.get("volume", 0))),
            })
        return bars
    except Exception as e:
        logger.warning(f"MT5 vendor call failed for {broker}: {e}")
        return None
