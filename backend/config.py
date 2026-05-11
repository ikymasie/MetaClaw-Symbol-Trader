"""
TradeClaw Configuration Management
Reads from ConfigManager (config.json) with .env fallback for backward compatibility.
Provides a mutable runtime config singleton.
"""

import os
import threading
from dataclasses import dataclass, field

from config_manager import config_manager

# Bootstrap the config manager on module load.
# This loads config.json (or creates it) and auto-migrates from .env if needed.
try:
    config_manager.bootstrap()
except Exception as _e:
    import logging
    logging.getLogger("tradeclaw.config").error(f"ConfigManager bootstrap failed: {_e}")


def _cfg(key: str, section: str = "", default: str = "") -> str:
    """Read a value from ConfigManager, falling back to env vars."""
    if section:
        val = config_manager._data.get(section, {}).get(key, "")
        if val:
            return str(val)
    return os.getenv(key.upper(), default)


def _cfg_api(key: str, default: str = "") -> str:
    """Read an API key from ConfigManager."""
    val = config_manager.get_api_key(key)
    return val if val else os.getenv(key.upper(), default)


def _cfg_default(key: str, default: str = "") -> str:
    """Read a trading default from ConfigManager."""
    val = config_manager.get_trading_defaults().get(key, "")
    if val:
        return str(val)
    return default


# Database URL — top-level for backward compatibility
DATABASE_URL = config_manager.get_database_url() or os.getenv("DATABASE_URL", "")


@dataclass
class TradingConfig:
    """Mutable trading configuration — can be updated from the UI at runtime."""

    # MetaTrader 5 credentials (from default account)
    mt5_login: int = field(default_factory=lambda: _get_default_mt5_login())
    mt5_password: str = field(default_factory=lambda: _get_default_mt5_password())
    mt5_server: str = field(default_factory=lambda: _get_default_mt5_server())

    # Trading params
    symbol: str = field(default_factory=lambda: _cfg_default("symbol", os.getenv("DEFAULT_SYMBOL", "SPY")))
    qty: float = field(
        default_factory=lambda: float(_cfg_default("qty", os.getenv("DEFAULT_QTY", "1.0")))
    )
    max_daily_drawdown_pct: float = field(
        default_factory=lambda: float(
            _cfg_default("max_daily_drawdown_pct", os.getenv("MAX_DAILY_DRAWDOWN_PCT", "6.0"))
        )
    )
    stop_loss_pct: float = field(
        default_factory=lambda: float(
            _cfg_default("stop_loss_pct", os.getenv("DEFAULT_STOP_LOSS_PCT", "1.0"))
        )
    )
    bb_period: int = field(
        default_factory=lambda: int(
            _cfg_default("bb_period", os.getenv("DEFAULT_BB_PERIOD", "20"))
        )
    )
    bb_std_dev: float = field(
        default_factory=lambda: float(
            _cfg_default("bb_std_dev", os.getenv("DEFAULT_BB_STD_DEV", "2.0"))
        )
    )

    # ── Fibonacci Retracement Config ──────────────────────────────────────
    fib_enabled: bool = field(
        default_factory=lambda: os.getenv("FIB_ENABLED", "true").lower() == "true"
    )
    fib_lookback_bars: int = field(
        default_factory=lambda: int(os.getenv("FIB_LOOKBACK_BARS", "50"))
    )
    fib_bounce_threshold_pct: float = field(
        default_factory=lambda: float(os.getenv("FIB_BOUNCE_THRESHOLD_PCT", "0.20"))
    )
    fib_entry_mode: str = field(
        default_factory=lambda: os.getenv("FIB_ENTRY_MODE", "AND")
    )
    fib_active_levels_raw: str = field(
        default_factory=lambda: os.getenv("FIB_ACTIVE_LEVELS", "23.6,38.2,50.0,61.8")
    )

    # ── Regime Detector Config ─────────────────────────────────────────────
    regime_filter_enabled: bool = field(
        default_factory=lambda: os.getenv("REGIME_FILTER_ENABLED", "true").lower() == "true"
    )
    adx_period: int = field(
        default_factory=lambda: int(os.getenv("ADX_PERIOD", "14"))
    )
    adx_trend_threshold: float = field(
        default_factory=lambda: float(os.getenv("ADX_TREND_THRESHOLD", "25.0"))
    )

    # ── Momentum Filter Config ─────────────────────────────────────────────
    momentum_filter_enabled: bool = field(
        default_factory=lambda: os.getenv("MOMENTUM_FILTER_ENABLED", "true").lower() == "true"
    )
    ema_fast: int = field(
        default_factory=lambda: int(os.getenv("EMA_FAST", "8"))
    )
    ema_mid: int = field(
        default_factory=lambda: int(os.getenv("EMA_MID", "21"))
    )
    ema_slow: int = field(
        default_factory=lambda: int(os.getenv("EMA_SLOW", "55"))
    )

    # ── Sentiment Context Config ───────────────────────────────────────────
    sentiment_context_enabled: bool = field(
        default_factory=lambda: os.getenv("SENTIMENT_CONTEXT_ENABLED", "true").lower() == "true"
    )

    # ── Kelly Criterion Position Sizer ─────────────────────────────────────
    kelly_sizing_enabled: bool = field(
        default_factory=lambda: os.getenv("KELLY_SIZING_ENABLED", "true").lower() == "true"
    )
    kelly_fraction: float = field(
        default_factory=lambda: float(os.getenv("KELLY_FRACTION", "0.25"))
    )

    # ── VWAP Analyser ──────────────────────────────────────────────────────
    vwap_enabled: bool = field(
        default_factory=lambda: os.getenv("VWAP_ENABLED", "true").lower() == "true"
    )
    vwap_entry_sd: float = field(
        default_factory=lambda: float(os.getenv("VWAP_ENTRY_SD", "2.5"))
    )
    vwap_entry_mode: str = field(
        default_factory=lambda: os.getenv("VWAP_ENTRY_MODE", "AND")
    )

    @property
    def fib_active_levels(self) -> list[float]:
        """Parse the comma-separated active Fib levels into a list of floats."""
        try:
            return [float(x.strip()) for x in self.fib_active_levels_raw.split(",") if x.strip()]
        except ValueError:
            return [23.6, 38.2, 50.0, 61.8]

    # ── AI Brain ──────────────────────────────────────────────────────────
    openclaw_base_url: str = field(
        default_factory=lambda: os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789")
    )
    openclaw_token: str = field(
        default_factory=lambda: _cfg_api("gemini_api_key", os.getenv("OPENCLAW_TOKEN", ""))
    )
    openclaw_model: str = field(
        default_factory=lambda: _cfg_api("gemini_model", os.getenv("OPENCLAW_MODEL", "google/gemini-flash-latest"))
    )
    deep_think_model: str = field(
        default_factory=lambda: os.getenv("DEEP_THINK_MODEL", "gemini-3.1-pro")
    )
    quick_think_model: str = field(
        default_factory=lambda: os.getenv("QUICK_THINK_MODEL", "gemini-3.1-flash-preview")
    )
    ollama_base_url: str = field(
        default_factory=lambda: _get_ollama("base_url", os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    )
    ollama_model: str = field(
        default_factory=lambda: _get_ollama("model", os.getenv("OLLAMA_MODEL", "ollama/gemma4:e4b"))
    )
    ollama_model_name: str = field(
        default_factory=lambda: _get_ollama("model_name", os.getenv("OLLAMA_MODEL_NAME", "gemma2:4b"))
    )
    ai_brain_enabled: bool = field(
        default_factory=lambda: _get_ai_brain_enabled()
    )
    ai_interval_minutes: int = field(
        default_factory=lambda: _get_ai_interval()
    )
    ai_min_trades_trigger: int = field(
        default_factory=lambda: int(os.getenv("AI_MIN_TRADES_TRIGGER", "10"))
    )
    ai_loss_streak_trigger: int = field(
        default_factory=lambda: int(os.getenv("AI_LOSS_STREAK_TRIGGER", "3"))
    )

    # Thread-safe lock for runtime updates
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, **kwargs):
        """Thread-safe config update."""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self, key) and not key.startswith("_"):
                    setattr(self, key, value)

    def snapshot(self) -> dict:
        """Return a thread-safe snapshot of trading config values."""
        with self._lock:
            return {
                "symbol": self.symbol,
                "qty": self.qty,
                "stop_loss_pct": self.stop_loss_pct,
                "bb_period": self.bb_period,
                "bb_std_dev": self.bb_std_dev,
                "max_daily_drawdown_pct": self.max_daily_drawdown_pct,
                # Fibonacci Retracement Config
                "fib_enabled": self.fib_enabled,
                "fib_lookback_bars": self.fib_lookback_bars,
                "fib_bounce_threshold_pct": self.fib_bounce_threshold_pct,
                "fib_entry_mode": self.fib_entry_mode,
                "fib_active_levels": self.fib_active_levels,
                # Regime Detector Config
                "regime_filter_enabled": self.regime_filter_enabled,
                "adx_period": self.adx_period,
                "adx_trend_threshold": self.adx_trend_threshold,
                # Momentum Filter Config
                "momentum_filter_enabled": self.momentum_filter_enabled,
                "ema_fast": self.ema_fast,
                "ema_mid": self.ema_mid,
                "ema_slow": self.ema_slow,
                # Kelly Sizing Config
                "kelly_sizing_enabled": self.kelly_sizing_enabled,
                "kelly_fraction": self.kelly_fraction,
                # VWAP Analyser Config
                "vwap_enabled": self.vwap_enabled,
                "vwap_entry_sd": self.vwap_entry_sd,
                "vwap_entry_mode": self.vwap_entry_mode,
            }

    def ai_snapshot(self) -> dict:
        """Return a thread-safe snapshot of AI Brain config values."""
        with self._lock:
            return {
                "openclaw_base_url": self.openclaw_base_url,
                "openclaw_token": self.openclaw_token,
                "openclaw_model": self.openclaw_model,
                "deep_think_model": self.deep_think_model,
                "quick_think_model": self.quick_think_model,
                "ollama_base_url": self.ollama_base_url,
                "ollama_model": self.ollama_model,
                "ollama_model_name": self.ollama_model_name,
                "ai_brain_enabled": self.ai_brain_enabled,
                "ai_interval_minutes": self.ai_interval_minutes,
                "ai_min_trades_trigger": self.ai_min_trades_trigger,
                "ai_loss_streak_trigger": self.ai_loss_streak_trigger,
            }

    # ── Database ──────────────────────────────────────────────────────────
    database_url: str = field(
        default_factory=lambda: config_manager.get_database_url() or os.getenv("DATABASE_URL", "")
    )


# ── Helper Functions ──────────────────────────────────────────────────────

def _get_default_mt5_login() -> int:
    """Get MT5 login from the default account in ConfigManager."""
    acct = config_manager.get_default_account()
    if acct:
        return acct.get("mt5_login", 0)
    return int(os.getenv("MT5_LOGIN", "0") or "0")


def _get_default_mt5_password() -> str:
    acct = config_manager.get_default_account()
    if acct:
        return acct.get("mt5_password", "")
    return os.getenv("MT5_PASSWORD", "")


def _get_default_mt5_server() -> str:
    acct = config_manager.get_default_account()
    if acct:
        return acct.get("mt5_server", "")
    return os.getenv("MT5_SERVER", "")


def _get_ollama(key: str, default: str) -> str:
    """Read Ollama config from ConfigManager."""
    val = config_manager._data.get("ollama", {}).get(key, "")
    return val if val else default


def _get_ai_brain_enabled() -> bool:
    """Read AI brain enabled state from ConfigManager."""
    val = config_manager._data.get("ai_brain", {}).get("enabled")
    if val is not None:
        return bool(val)
    return os.getenv("AI_BRAIN_ENABLED", "true").lower() == "true"


def _get_ai_interval() -> int:
    """Read AI analysis interval from ConfigManager."""
    val = config_manager._data.get("ai_brain", {}).get("analysis_interval_minutes")
    if val is not None:
        return int(val)
    return int(os.getenv("AI_ANALYSIS_INTERVAL_MINUTES", "60"))


# Singleton config instance
config = TradingConfig()
