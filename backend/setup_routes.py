"""
TradeClaw — Setup API Routes
==============================
First-run setup wizard endpoints:
  /setup/status     — Check setup progress
  /setup/database   — Save & test database connection
  /setup/api-keys   — Save API keys (Gemini, Alpaca)
  /setup/complete   — Mark setup as done, trigger schema init
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config_manager import config_manager

logger = logging.getLogger("tradeclaw.setup")

router = APIRouter(prefix="/setup", tags=["setup"])


# ── Pydantic Models ───────────────────────────────────────────────────────

class SetupStatus(BaseModel):
    setup_complete: bool
    has_database: bool
    has_accounts: bool
    has_api_keys: bool
    account_count: int


class DatabaseConfig(BaseModel):
    url: str = Field(..., min_length=10, description="PostgreSQL connection string")


class DatabaseTestRequest(BaseModel):
    url: str = Field(..., min_length=10, description="PostgreSQL connection string to test")


class ApiKeysConfig(BaseModel):
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    deep_think_model: Optional[str] = None
    quick_think_model: Optional[str] = None
    alpaca_news_api_key: Optional[str] = None


class AiConfig(BaseModel):
    enabled: Optional[bool] = None
    analysis_interval_minutes: Optional[int] = Field(default=None, ge=5, le=1440)
    gemini_model: Optional[str] = None
    deep_think_model: Optional[str] = None
    quick_think_model: Optional[str] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None
    ollama_model_name: Optional[str] = None


class TradingDefaultsConfig(BaseModel):
    symbol: Optional[str] = None
    qty: Optional[float] = Field(default=None, gt=0)
    stop_loss_pct: Optional[float] = Field(default=None, ge=0.1, le=10.0)
    bb_period: Optional[int] = Field(default=None, ge=5, le=200)
    bb_std_dev: Optional[float] = Field(default=None, ge=0.5, le=5.0)
    max_daily_drawdown_pct: Optional[float] = Field(default=None, ge=0.5, le=50.0)


class Mt5Config(BaseModel):
    symbol_suffix: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/status", response_model=SetupStatus)
async def get_setup_status():
    """Check the current setup progress."""
    return config_manager.get_setup_status()


@router.post("/database")
async def save_database_config(body: DatabaseConfig):
    """Save the database URL after testing the connection."""
    # Test first
    success, message = await _test_db_connection(body.url)
    if not success:
        raise HTTPException(status_code=400, detail=f"Connection failed: {message}")

    config_manager.set_database_url(body.url)
    return {"status": "saved", "message": "Database URL saved and connection verified"}


@router.post("/database/test")
async def test_database_connection(body: DatabaseTestRequest):
    """Test a database connection string without saving."""
    success, message = await _test_db_connection(body.url)
    return {
        "connected": success,
        "message": message,
    }


@router.post("/api-keys")
async def save_api_keys(body: ApiKeysConfig):
    """Save API keys (Gemini, Alpaca, etc.)."""
    keys = {}
    if body.gemini_api_key is not None:
        keys["gemini_api_key"] = body.gemini_api_key
    if body.gemini_model is not None:
        keys["gemini_model"] = body.gemini_model
    if body.deep_think_model is not None:
        keys["deep_think_model"] = body.deep_think_model
    if body.quick_think_model is not None:
        keys["quick_think_model"] = body.quick_think_model
    if body.alpaca_news_api_key is not None:
        keys["alpaca_news_api_key"] = body.alpaca_news_api_key

    if not keys:
        raise HTTPException(status_code=400, detail="No keys provided")

    config_manager.set_api_keys(keys)
    return {"status": "saved", "keys_updated": list(keys.keys())}


@router.get("/api-keys")
async def get_api_keys():
    """Return API keys (masked for display)."""
    return config_manager.get_api_keys()


@router.post("/complete")
async def complete_setup():
    """
    Mark setup as complete.
    Triggers database schema initialization and starts trading subsystems.
    """
    status = config_manager.get_setup_status()

    # Validate minimum requirements
    if not status["has_database"]:
        raise HTTPException(
            status_code=400,
            detail="Cannot complete setup: database URL not configured",
        )
    if not status["has_accounts"]:
        raise HTTPException(
            status_code=400,
            detail="Cannot complete setup: no MT5 accounts configured",
        )

    # Initialize the database schema
    try:
        db_url = config_manager.get_database_url()
        from postgres_store import init_db
        await init_db(db_url)
        logger.info("[Setup] Database schema initialized successfully")
    except Exception as e:
        logger.error(f"[Setup] Database schema init failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Database initialization failed: {str(e)}",
        )

    config_manager.complete_setup()

    return {
        "status": "complete",
        "message": "Setup complete! TradeClaw is ready to trade.",
    }


@router.get("/config")
async def get_full_config():
    """Return the full config (masked) for the settings page."""
    return config_manager.get_full_config()


@router.post("/ai")
async def update_ai_config(body: AiConfig):
    """Update AI brain / Ollama configuration."""
    ai_update = {}
    if body.enabled is not None or body.analysis_interval_minutes is not None:
        brain = {}
        if body.enabled is not None:
            brain["enabled"] = body.enabled
        if body.analysis_interval_minutes is not None:
            brain["analysis_interval_minutes"] = body.analysis_interval_minutes
        ai_update["ai_brain"] = brain

    if body.ollama_base_url is not None or body.ollama_model is not None or body.ollama_model_name is not None:
        ollama = {}
        if body.ollama_base_url is not None:
            ollama["base_url"] = body.ollama_base_url
        if body.ollama_model is not None:
            ollama["model"] = body.ollama_model
        if body.ollama_model_name is not None:
            ollama["model_name"] = body.ollama_model_name
        ai_update["ollama"] = ollama

    if body.gemini_model is not None:
        ai_update["gemini_model"] = body.gemini_model
    if body.deep_think_model is not None:
        ai_update["deep_think_model"] = body.deep_think_model
    if body.quick_think_model is not None:
        ai_update["quick_think_model"] = body.quick_think_model

    if not ai_update:
        raise HTTPException(status_code=400, detail="No AI config values provided")

    config_manager.set_ai_config(ai_update)
    return {"status": "saved", "updated": list(ai_update.keys())}


@router.get("/ai")
async def get_ai_config():
    """Return AI brain configuration."""
    return config_manager.get_ai_config()


@router.post("/trading-defaults")
async def update_trading_defaults(body: TradingDefaultsConfig):
    """Update trading default values."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No values provided")
    config_manager.set_trading_defaults(updates)
    return {"status": "saved", "updated": list(updates.keys())}


@router.get("/trading-defaults")
async def get_trading_defaults():
    """Return trading default values."""
    return config_manager.get_trading_defaults()


@router.post("/mt5")
async def update_mt5_config(body: Mt5Config):
    """Update MT5 settings (symbol suffix, etc.)."""
    if body.symbol_suffix is not None:
        config_manager.set_mt5_symbol_suffix(body.symbol_suffix)
    return {"status": "saved"}


# ── Helpers ───────────────────────────────────────────────────────────────

async def _test_db_connection(url: str) -> tuple[bool, str]:
    """Test a PostgreSQL connection. Returns (success, message)."""
    try:
        import asyncpg
        conn = await asyncio.wait_for(
            asyncpg.connect(url),
            timeout=10.0,
        )
        version = await conn.fetchval("SELECT version()")
        await conn.close()
        return True, f"Connected to PostgreSQL: {version[:60]}..."
    except asyncio.TimeoutError:
        return False, "Connection timed out after 10 seconds"
    except Exception as e:
        return False, str(e)
