"""
TradeClaw — Account API Routes
================================
CRUD for MT5 broker accounts:
  /accounts          — List / Add accounts
  /accounts/{id}     — Get / Update / Delete
  /accounts/{id}/test    — Test MT5 connection
  /accounts/{id}/symbols — Fetch available symbols from broker
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config_manager import config_manager

logger = logging.getLogger("tradeclaw.accounts")

router = APIRouter(prefix="/accounts", tags=["accounts"])


# ── Pydantic Models ───────────────────────────────────────────────────────

class AccountCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=100, description="Human-friendly name")
    mt5_login: int = Field(..., gt=0, description="MT5 account login number")
    mt5_password: str = Field(..., min_length=1, description="MT5 account password")
    mt5_server: str = Field(..., min_length=1, description="MT5 broker server name")
    is_default: bool = False


class AccountUpdate(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=100)
    mt5_login: Optional[int] = Field(default=None, gt=0)
    mt5_password: Optional[str] = Field(default=None, min_length=1)
    mt5_server: Optional[str] = Field(default=None, min_length=1)
    is_default: Optional[bool] = None


class AccountTestRequest(BaseModel):
    mt5_login: Optional[int] = None
    mt5_password: Optional[str] = None
    mt5_server: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("")
async def list_accounts():
    """List all MT5 broker accounts (passwords masked)."""
    accounts = config_manager.list_accounts()
    return {"accounts": accounts, "count": len(accounts)}


@router.post("")
async def add_account(body: AccountCreate):
    """
    Add a new MT5 broker account.
    Tests the connection before saving.
    """
    # Test connection first
    success, message, info = await _test_mt5_credentials(
        body.mt5_login, body.mt5_password, body.mt5_server
    )
    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"MT5 connection test failed: {message}",
        )

    account_id = config_manager.add_account(body.model_dump())

    return {
        "status": "created",
        "account_id": account_id,
        "label": body.label,
        "connection_test": {
            "connected": True,
            "message": message,
            "info": info,
        },
    }


@router.get("/{account_id}")
async def get_account(account_id: str):
    """Get a single account by ID (password masked)."""
    accounts = config_manager.list_accounts()
    for acct in accounts:
        if acct["id"] == account_id:
            return acct
    raise HTTPException(status_code=404, detail=f"Account {account_id} not found")


@router.patch("/{account_id}")
async def update_account(account_id: str, body: AccountUpdate):
    """Update an existing account's details."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # If password or login changed, test the connection
    if "mt5_login" in updates or "mt5_password" in updates or "mt5_server" in updates:
        # Get existing account for merge
        existing = config_manager.get_account(account_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

        test_login = updates.get("mt5_login", existing["mt5_login"])
        test_pass = updates.get("mt5_password", existing["mt5_password"])
        test_server = updates.get("mt5_server", existing["mt5_server"])

        success, message, _ = await _test_mt5_credentials(test_login, test_pass, test_server)
        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"MT5 connection test failed with new credentials: {message}",
            )

    if not config_manager.update_account(account_id, updates):
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

    return {"status": "updated", "account_id": account_id}


@router.delete("/{account_id}")
async def delete_account(account_id: str):
    """
    Remove an account from config (database record only).
    Does NOT delete the actual MT5 broker account.
    """
    if not config_manager.remove_account(account_id):
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

    return {
        "status": "deleted",
        "account_id": account_id,
        "message": "Account removed from TradeClaw config. Your broker account is unaffected.",
    }


@router.post("/{account_id}/test")
async def test_account_connection(account_id: str):
    """Test the MT5 connection for a saved account."""
    account = config_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

    success, message, info = await _test_mt5_credentials(
        account["mt5_login"],
        account["mt5_password"],
        account["mt5_server"],
    )

    return {
        "account_id": account_id,
        "connected": success,
        "message": message,
        "info": info,
    }


@router.get("/{account_id}/symbols")
async def get_account_symbols(account_id: str):
    """
    Fetch available trading symbols from the broker via MT5.
    Temporarily connects to this account's MT5 terminal to enumerate symbols.
    """
    account = config_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

    try:
        symbols = await _fetch_symbols_for_account(
            account["mt5_login"],
            account["mt5_password"],
            account["mt5_server"],
        )
        return {
            "account_id": account_id,
            "symbols": symbols,
            "count": len(symbols),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch symbols: {str(e)}",
        )


@router.post("/test")
async def test_new_credentials(body: AccountTestRequest):
    """Test MT5 credentials before creating an account."""
    if not body.mt5_login or not body.mt5_password or not body.mt5_server:
        raise HTTPException(
            status_code=400,
            detail="mt5_login, mt5_password, and mt5_server are all required",
        )

    success, message, info = await _test_mt5_credentials(
        body.mt5_login, body.mt5_password, body.mt5_server
    )
    return {
        "connected": success,
        "message": message,
        "info": info,
    }


# ── Helpers ───────────────────────────────────────────────────────────────

async def _test_mt5_credentials(
    login: int,
    password: str,
    server: str,
) -> tuple[bool, str, dict]:
    """
    Test MT5 credentials by connecting to the terminal.
    Returns (success, message, account_info).

    NOTE: This uses the running MT5 terminal — it re-logins temporarily
    and then switches back to the default account afterward.
    """
    try:
        from mt5_bridge import mt5

        # Try initializing the terminal
        if not mt5.initialize():
            terminal_path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
            if not mt5.initialize(path=terminal_path):
                return False, f"Cannot connect to MT5 terminal: {mt5.last_error()}", {}

        # Attempt login with provided credentials
        if not mt5.login(login, password=password, server=server):
            err = mt5.last_error()
            return False, f"Login failed: {err}", {}

        # Gather account info
        account_info = mt5.account_info()
        info = {}
        if account_info:
            info = {
                "login": account_info.login,
                "name": account_info.name,
                "server": account_info.server,
                "balance": account_info.balance,
                "equity": account_info.equity,
                "currency": account_info.currency,
                "leverage": account_info.leverage,
                "trade_mode": account_info.trade_mode,
                "trade_allowed": account_info.trade_allowed,
                "trade_expert": account_info.trade_expert,
            }

        # Switch back to default account
        default = config_manager.get_default_account()
        if default and default["mt5_login"] != login:
            mt5.login(
                default["mt5_login"],
                password=default["mt5_password"],
                server=default["mt5_server"],
            )

        trade_status = "AutoTrading ENABLED ✅" if info.get("trade_expert") else "AutoTrading DISABLED ⚠️"
        message = (
            f"Connected! {info.get('name', '')} — "
            f"Balance: {info.get('currency', '$')}{info.get('balance', 0):,.2f} — "
            f"{trade_status}"
        )
        return True, message, info

    except Exception as e:
        logger.error(f"[Accounts] MT5 test failed: {e}")
        return False, f"Connection error: {str(e)}", {}


async def _fetch_symbols_for_account(
    login: int,
    password: str,
    server: str,
) -> list[dict]:
    """
    Connect to an MT5 account and fetch all available symbols.
    Groups symbols by their category (path prefix).
    """
    try:
        from mt5_bridge import mt5

        if not mt5.initialize():
            terminal_path = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
            if not mt5.initialize(path=terminal_path):
                raise RuntimeError(f"Cannot connect to MT5 terminal: {mt5.last_error()}")

        if not mt5.login(login, password=password, server=server):
            raise RuntimeError(f"Login failed: {mt5.last_error()}")

        symbols = mt5.symbols_get()
        if symbols is None:
            return []

        result = []
        for s in symbols:
            # Determine category from path
            path = getattr(s, "path", "")
            category = path.split("\\")[0] if "\\" in path else "Other"

            result.append({
                "name": s.name,
                "broker_symbol": s.name,
                "category": category,
                "path": path,
                "description": getattr(s, "description", ""),
                "digits": getattr(s, "digits", 0),
                "spread": getattr(s, "spread", 0),
                "trade_mode": getattr(s, "trade_mode", 0),
                "volume_min": getattr(s, "volume_min", 0.01) or 0.01,
                "volume_max": getattr(s, "volume_max", 100.0) or 100.0,
                "volume_step": getattr(s, "volume_step", 0.01) or 0.01,
            })

        # Switch back to default account
        default = config_manager.get_default_account()
        if default and default["mt5_login"] != login:
            mt5.login(
                default["mt5_login"],
                password=default["mt5_password"],
                server=default["mt5_server"],
            )

        return result

    except Exception as e:
        logger.error(f"[Accounts] Symbol fetch failed: {e}")
        raise
