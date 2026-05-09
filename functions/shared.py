"""
TradeClaw — Shared Utilities for Cloud Functions
=================================================
Lightweight Postgres init + helpers shared by all scheduled functions.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import asyncpg

logger = logging.getLogger("tradeclaw.functions")
logging.basicConfig(level=logging.INFO)

_pool: Optional[asyncpg.Pool] = None

async def get_db_pool() -> asyncpg.Pool:
    """Initialize and return an asyncpg connection pool."""
    global _pool
    if _pool is not None:
        return _pool
        
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is missing.")
        
    logger.info("Initializing Postgres connection pool...")
    _pool = await asyncpg.create_pool(dsn=db_url, min_size=1, max_size=10)
    return _pool

def get_user_id() -> str:
    """Return the tenant user ID from environment (matches backend convention)."""
    return os.getenv("METACLAW_USER_ID", "default_user")

def symbol_to_key(symbol: str) -> str:
    """Normalize a trading symbol into a safe string."""
    return symbol.replace("/", "-").upper()

def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()
