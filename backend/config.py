"""
TradeClaw Configuration Management
Loads environment variables and provides a mutable runtime config.
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv
import threading

load_dotenv()


@dataclass
class TradingConfig:
    """Mutable trading configuration — can be updated from the UI at runtime."""

    # MetaTrader 5 credentials
    mt5_login: int = field(default_factory=lambda: int(os.getenv("MT5_LOGIN", "0") or "0"))
    mt5_password: str = field(default_factory=lambda: os.getenv("MT5_PASSWORD", ""))
    mt5_server: str = field(default_factory=lambda: os.getenv("MT5_SERVER", ""))

    # Trading params
    symbol: str = field(default_factory=lambda: os.getenv("DEFAULT_SYMBOL", "SPY"))
    qty: float = field(
        default_factory=lambda: float(os.getenv("DEFAULT_QTY", "1.0"))
    )
    max_daily_drawdown_pct: float = field(
        default_factory=lambda: float(os.getenv("MAX_DAILY_DRAWDOWN_PCT", "6.0"))
    )
    stop_loss_pct: float = field(
        default_factory=lambda: float(os.getenv("DEFAULT_STOP_LOSS_PCT", "1.0"))
    )
    bb_period: int = field(
        default_factory=lambda: int(os.getenv("DEFAULT_BB_PERIOD", "20"))
    )
    bb_std_dev: float = field(
        default_factory=lambda: float(os.getenv("DEFAULT_BB_STD_DEV", "2.0"))
    )

    # Mode
    demo_mode: bool = True

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
    # "AND" = Fib + BB must both agree; "OR" = either signal can trigger entry
    fib_entry_mode: str = field(
        default_factory=lambda: os.getenv("FIB_ENTRY_MODE", "AND")
    )
    # Comma-separated list of active Fib levels, e.g. "23.6,38.2,50.0,61.8"
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
    # Minimum standard deviations from VWAP required to flag an entry zone
    # 2.5 = institutional standard; raise to 3.0 for stricter filtering
    vwap_entry_sd: float = field(
        default_factory=lambda: float(os.getenv("VWAP_ENTRY_SD", "2.5"))
    )
    # "AND" = BB + VWAP must both confirm; "OR" = either can trigger alone
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
        default_factory=lambda: os.getenv("OPENCLAW_TOKEN", "")
    )
    openclaw_model: str = field(
        default_factory=lambda: os.getenv("OPENCLAW_MODEL", "google/gemini-flash-latest")
    )
    ollama_base_url: str = field(
        default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    # Model name used via OpenClaw proxy for Ollama
    ollama_model: str = field(
        default_factory=lambda: os.getenv("OLLAMA_MODEL", "ollama/gemma4:e4b")
    )
    # Model name used for direct Ollama REST API fallback
    ollama_model_name: str = field(
        default_factory=lambda: os.getenv("OLLAMA_MODEL_NAME", "gemma2:4b")
    )
    ai_brain_enabled: bool = field(
        default_factory=lambda: os.getenv("AI_BRAIN_ENABLED", "true").lower() == "true"
    )
    ai_interval_minutes: int = field(
        default_factory=lambda: int(os.getenv("AI_ANALYSIS_INTERVAL_MINUTES", "60"))
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
                "demo_mode": self.demo_mode,
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
                "ollama_base_url": self.ollama_base_url,
                "ollama_model": self.ollama_model,
                "ollama_model_name": self.ollama_model_name,
                "ai_brain_enabled": self.ai_brain_enabled,
                "ai_interval_minutes": self.ai_interval_minutes,
                "ai_min_trades_trigger": self.ai_min_trades_trigger,
                "ai_loss_streak_trigger": self.ai_loss_streak_trigger,
            }


# Singleton config instance
config = TradingConfig()
