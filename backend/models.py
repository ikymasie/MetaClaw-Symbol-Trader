"""
TradeClaw Pydantic Models
Request/Response schemas for the FastAPI endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class MT5Credentials(BaseModel):
    login: int
    password: str
    server: str


class BrokerAccount(BaseModel):
    id: str = Field(..., description="Unique ID for this broker account")
    name: str = Field(..., description="User-friendly name (e.g., 'Weltrade Live')")
    login: int
    server: str
    is_active: bool = True
    created_at: str = ""


class BotStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    CRITICAL_STOP = "CRITICAL_STOP"
    ORGAN_FAILURE = "ORGAN_FAILURE"
    STARTING = "STARTING"
    STOPPING = "STOPPING"


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    STOP_LOSS = "STOP_LOSS"
    DRAWDOWN_HALT = "DRAWDOWN_HALT"


# ---- Request Models ----

class StartRequest(BaseModel):
    pass


class ConfigUpdate(BaseModel):
    qty: Optional[float] = None
    capital_allocation: Optional[float] = None


# ---- Response Models ----

class ConfigSnapshot(BaseModel):
    # Core strategy
    symbol: str
    qty: float
    stop_loss_pct: float
    bb_period: int
    bb_std_dev: float
    max_daily_drawdown_pct: float

    # Capital / Identity
    account_id: Optional[str] = None
    capital_allocation: Optional[float] = 0.0
    description: str = ""
    personality: str = ""
    animal: str = ""
    category: str = ""

    # Fibonacci
    fib_enabled: bool = True
    fib_lookback_bars: int = 50
    fib_bounce_threshold_pct: float = 0.20
    fib_entry_mode: str = "AND"
    fib_active_levels: list[float] = []

    # Regime
    regime_filter_enabled: bool = True
    adx_period: int = 14
    adx_trend_threshold: float = 25.0

    # Momentum
    momentum_filter_enabled: bool = True
    ema_fast: int = 8
    ema_mid: int = 21
    ema_slow: int = 55

    # Kelly
    kelly_sizing_enabled: bool = True
    kelly_fraction: float = 0.25

    # VWAP
    vwap_enabled: bool = True
    vwap_entry_sd: float = 2.5
    vwap_entry_mode: str = "AND"


class StatusResponse(BaseModel):
    bot_status: BotStatus
    current_price: float = 0.0
    position_qty: float = 0.0
    position_side: Optional[str] = None
    entry_price: float = 0.0
    equity: float = 0.0
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0
    daily_drawdown_pct: float = 0.0
    unrealized_pnl: float = 0.0
    starting_equity: float = 0.0
    last_signal: Optional[str] = None
    total_trades_today: int = 0
    win_rate: float = 0.0
    config: ConfigSnapshot
    timestamp: str = ""
    message: str = ""
    # Persona fields duplicated for snapshot convenience
    description: str = ""
    personality: str = ""
    animal: str = ""
    category: str = ""
    ai_generated: bool = False


class TradeRecord(BaseModel):
    id: int = 0
    timestamp: str
    side: str
    symbol: str
    qty: float
    price: float
    pnl: float = 0.0
    signal: str = ""


class PricePoint(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float


class MarkerPoint(BaseModel):
    time: str
    position: str  # "aboveBar" or "belowBar"
    color: str
    shape: str  # "arrowUp", "arrowDown", "circle"
    text: str


class EquityPoint(BaseModel):
    time: str
    equity: float
    daily_pnl: float = 0.0


class BollingerData(BaseModel):
    time: str
    upper: float
    middle: float
    lower: float


class HistoryResponse(BaseModel):
    trades: list[TradeRecord] = []
    equity_curve: list[EquityPoint] = []
    price_data: list[PricePoint] = []
    markers: list[MarkerPoint] = []
    bollinger: list[BollingerData] = []
