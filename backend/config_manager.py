"""
TradeClaw — ConfigManager
==========================
Persistent configuration layer backed by a JSON file on a Docker volume.
Replaces .env-based configuration with a UI-driven, runtime-editable config.

Config stored at:   /app/data/config.json   (persisted via Docker volume)
Encryption key at:  /app/data/.keyfile       (auto-generated on first run)
"""

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from cryptography.fernet import Fernet

logger = logging.getLogger("tradeclaw.config_manager")

# Default paths — overridable via environment for testing.
# In Docker, TRADECLAW_DATA_DIR points to /app/backend/data.
# Locally, fall back to ./data relative to this file's directory.
_DEFAULT_DATA_DIR = (
    "/app/backend/data"
    if Path("/app/backend/data").exists()
    else str(Path(__file__).resolve().parent / "data")
)
DATA_DIR = Path(os.getenv("TRADECLAW_DATA_DIR", _DEFAULT_DATA_DIR))
CONFIG_PATH = DATA_DIR / "config.json"
KEYFILE_PATH = DATA_DIR / ".keyfile"


def _default_config() -> dict:
    """Return a clean default config skeleton for first-run."""
    return {
        "setup_complete": False,
        "accounts": [],
        "api_keys": {
            "gemini_api_key": "",
            "gemini_model": "gemini-3.1-flash-lite",
            "deep_think_model": "gemini-3.1-pro",
            "quick_think_model": "gemini-3.1-flash-preview",
            "alpaca_news_api_key": "",
        },
        "database": {
            "url": "",
        },
        "ai_brain": {
            "enabled": True,
            "analysis_interval_minutes": 60,
        },
        "ollama": {
            "base_url": "http://localhost:11434",
            "model": "ollama/gemma4:e4b",
            "model_name": "gemma2:4b",
        },
        "server": {
            "host": "0.0.0.0",
            "port": 8000,
        },
        "trading_defaults": {
            "symbol": "XAUUSD",
            "qty": 0.01,
            "stop_loss_pct": 1.0,
            "bb_period": 20,
            "bb_std_dev": 2.0,
            "max_daily_drawdown_pct": 6.0,
        },
        "mt5": {
            "symbol_suffix": "_i",
        },
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


class ConfigManager:
    """
    Thread-safe, file-backed configuration manager.

    - Reads from / writes to a JSON file on a Docker volume.
    - Passwords are encrypted at rest using Fernet (AES-128-CBC).
    - Supports an .env auto-migration path for existing deployments.
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        keyfile_path: Optional[Path] = None,
    ):
        self._config_path = config_path or CONFIG_PATH
        self._keyfile_path = keyfile_path or KEYFILE_PATH
        self._lock = threading.RLock()
        self._data: dict = {}
        self._fernet: Optional[Fernet] = None
        self._bootstrapped: bool = False

        # Auto-bootstrap so encryption is always available.
        # This is idempotent — safe to call bootstrap() again later.
        try:
            self.bootstrap()
        except Exception as exc:
            logger.warning(f"[ConfigManager] Auto-bootstrap deferred: {exc}")

    # ── Bootstrap ─────────────────────────────────────────────────────────

    def bootstrap(self) -> None:
        """
        Initialize the config manager:
        1. Ensure data directory exists
        2. Load or create encryption key
        3. Load config (or create default)
        4. Auto-migrate from .env if applicable

        Idempotent — safe to call multiple times.
        """
        if self._bootstrapped:
            return

        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_encryption()
        self._load()

        # Auto-migrate from .env if config is empty/first-run
        if not self._data.get("setup_complete"):
            self._try_env_migration()

        self._bootstrapped = True
        logger.info(
            f"[ConfigManager] Bootstrapped — "
            f"setup_complete={self._data.get('setup_complete')}, "
            f"accounts={len(self._data.get('accounts', []))}"
        )

    def _init_encryption(self) -> None:
        """Load or generate the Fernet encryption key."""
        if self._keyfile_path.exists():
            key = self._keyfile_path.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            self._keyfile_path.parent.mkdir(parents=True, exist_ok=True)
            self._keyfile_path.write_bytes(key)
            os.chmod(self._keyfile_path, 0o600)
            logger.info("[ConfigManager] Generated new encryption key")
        self._fernet = Fernet(key)

    def _load(self) -> None:
        """Load config from disk, or create a default config."""
        if self._config_path.exists():
            try:
                raw = self._config_path.read_text(encoding="utf-8")
                self._data = json.loads(raw)
                logger.info(f"[ConfigManager] Loaded config from {self._config_path}")
            except (json.JSONDecodeError, OSError) as exc:
                logger.error(f"[ConfigManager] Failed to load config: {exc}. Using defaults.")
                self._data = _default_config()
        else:
            self._data = _default_config()
            self._save()
            logger.info(f"[ConfigManager] Created default config at {self._config_path}")

    def _save(self) -> None:
        """Atomic write: write to temp file, then rename. Prevents corruption."""
        self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
        # Ensure the parent directory exists (handles first-run on local dev)
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._config_path.parent),
                suffix=".tmp",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, default=str)
            os.replace(tmp_path, str(self._config_path))
        except OSError as exc:
            logger.error(f"[ConfigManager] Failed to save config: {exc}")
            # Clean up temp file if rename failed
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # ── Encryption Helpers ────────────────────────────────────────────────

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string and return a base64 Fernet token."""
        if self._fernet is None:
            raise RuntimeError(
                "ConfigManager encryption not initialized. "
                "Call bootstrap() or check that the keyfile directory is writable."
            )
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a Fernet token back to plaintext."""
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except Exception:
            # If decryption fails (e.g. plaintext stored before encryption was added),
            # return the raw value — it might already be plaintext.
            return ciphertext

    # ── Setup Status ──────────────────────────────────────────────────────

    def is_setup_complete(self) -> bool:
        with self._lock:
            return bool(self._data.get("setup_complete", False))

    def complete_setup(self) -> None:
        with self._lock:
            self._data["setup_complete"] = True
            self._save()
        logger.info("[ConfigManager] Setup marked complete")

    def get_setup_status(self) -> dict:
        """Return granular setup status for each section."""
        with self._lock:
            return {
                "setup_complete": self._data.get("setup_complete", False),
                "has_database": bool(self._data.get("database", {}).get("url")),
                "has_accounts": len(self._data.get("accounts", [])) > 0,
                "has_api_keys": bool(
                    self._data.get("api_keys", {}).get("gemini_api_key")
                ),
                "account_count": len(self._data.get("accounts", [])),
            }

    # ── Database ──────────────────────────────────────────────────────────

    def get_database_url(self) -> str:
        with self._lock:
            return self._data.get("database", {}).get("url", "")

    def set_database_url(self, url: str) -> None:
        with self._lock:
            if "database" not in self._data:
                self._data["database"] = {}
            self._data["database"]["url"] = url
            self._save()
        logger.info("[ConfigManager] Database URL updated")

    # ── API Keys ──────────────────────────────────────────────────────────

    def get_api_keys(self) -> dict:
        """Return all API keys (values masked for safe display)."""
        with self._lock:
            keys = dict(self._data.get("api_keys", {}))
            masked = {}
            for k, v in keys.items():
                if v and isinstance(v, str) and len(v) > 8:
                    masked[k] = v[:4] + "•" * (len(v) - 8) + v[-4:]
                else:
                    masked[k] = v
            return masked

    def get_api_key(self, name: str) -> str:
        """Return a specific API key (unmasked)."""
        with self._lock:
            return self._data.get("api_keys", {}).get(name, "")

    def set_api_keys(self, keys: dict) -> None:
        """Bulk set/update API keys."""
        with self._lock:
            if "api_keys" not in self._data:
                self._data["api_keys"] = {}
            for k, v in keys.items():
                if v is not None:  # Don't overwrite with None
                    self._data["api_keys"][k] = v
            self._save()
        logger.info(f"[ConfigManager] API keys updated: {list(keys.keys())}")

    # ── MT5 Accounts ──────────────────────────────────────────────────────

    def list_accounts(self) -> list[dict]:
        """Return all MT5 accounts with passwords masked."""
        with self._lock:
            accounts = self._data.get("accounts", [])
            return [self._mask_account(a) for a in accounts]

    def get_account(self, account_id: str) -> Optional[dict]:
        """Return a single account by ID (with decrypted password)."""
        with self._lock:
            for acct in self._data.get("accounts", []):
                if acct.get("id") == account_id:
                    result = dict(acct)
                    result["mt5_password"] = self.decrypt(result.get("mt5_password", ""))
                    return result
        return None

    def get_default_account(self) -> Optional[dict]:
        """Return the account flagged as default, with decrypted password."""
        with self._lock:
            for acct in self._data.get("accounts", []):
                if acct.get("is_default", False):
                    result = dict(acct)
                    result["mt5_password"] = self.decrypt(result.get("mt5_password", ""))
                    return result
            # Fallback: return first account if no default is set
            accounts = self._data.get("accounts", [])
            if accounts:
                result = dict(accounts[0])
                result["mt5_password"] = self.decrypt(result.get("mt5_password", ""))
                return result
        return None

    def add_account(self, data: dict) -> str:
        """Add a new MT5 account. Returns the generated account ID."""
        account_id = f"acc-{uuid.uuid4().hex[:8]}"
        account = {
            "id": account_id,
            "label": data.get("label", "Unnamed Account"),
            "mt5_login": int(data.get("mt5_login", 0)),
            "mt5_password": self.encrypt(data.get("mt5_password", "")),
            "mt5_server": data.get("mt5_server", ""),
            "is_default": data.get("is_default", False),
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            accounts = self._data.get("accounts", [])
            # If this is the first account or marked default, clear other defaults
            if account["is_default"] or not accounts:
                account["is_default"] = True
                for a in accounts:
                    a["is_default"] = False
            accounts.append(account)
            self._data["accounts"] = accounts
            self._save()
        logger.info(f"[ConfigManager] Added account: {account_id} ({account['label']})")
        return account_id

    def update_account(self, account_id: str, data: dict) -> bool:
        """Update an existing account. Returns True if found and updated."""
        with self._lock:
            for i, acct in enumerate(self._data.get("accounts", [])):
                if acct.get("id") == account_id:
                    if "label" in data:
                        acct["label"] = data["label"]
                    if "mt5_login" in data:
                        acct["mt5_login"] = int(data["mt5_login"])
                    if "mt5_password" in data:
                        acct["mt5_password"] = self.encrypt(data["mt5_password"])
                    if "mt5_server" in data:
                        acct["mt5_server"] = data["mt5_server"]
                    if data.get("is_default"):
                        for a in self._data["accounts"]:
                            a["is_default"] = False
                        acct["is_default"] = True
                    self._data["accounts"][i] = acct
                    self._save()
                    logger.info(f"[ConfigManager] Updated account: {account_id}")
                    return True
        return False

    def remove_account(self, account_id: str) -> bool:
        """Remove an account by ID. Returns True if found and removed."""
        with self._lock:
            accounts = self._data.get("accounts", [])
            original_len = len(accounts)
            was_default = False
            for a in accounts:
                if a.get("id") == account_id and a.get("is_default"):
                    was_default = True
            self._data["accounts"] = [a for a in accounts if a.get("id") != account_id]
            if len(self._data["accounts"]) < original_len:
                # If we removed the default, promote the first remaining account
                if was_default and self._data["accounts"]:
                    self._data["accounts"][0]["is_default"] = True
                self._save()
                logger.info(f"[ConfigManager] Removed account: {account_id}")
                return True
        return False

    def _mask_account(self, account: dict) -> dict:
        """Return an account dict with password masked for API display."""
        masked = dict(account)
        if masked.get("mt5_password"):
            masked["mt5_password"] = "••••••••"
        return masked

    # ── Ollama / AI Config ────────────────────────────────────────────────

    def get_ai_config(self) -> dict:
        with self._lock:
            return {
                "ai_brain": dict(self._data.get("ai_brain", {})),
                "ollama": dict(self._data.get("ollama", {})),
                "gemini_model": self._data.get("api_keys", {}).get("gemini_model", ""),
                "deep_think_model": self._data.get("api_keys", {}).get("deep_think_model", ""),
                "quick_think_model": self._data.get("api_keys", {}).get("quick_think_model", ""),
            }

    def set_ai_config(self, ai_config: dict) -> None:
        with self._lock:
            if "ai_brain" in ai_config:
                self._data.setdefault("ai_brain", {}).update(ai_config["ai_brain"])
            if "ollama" in ai_config:
                self._data.setdefault("ollama", {}).update(ai_config["ollama"])
            if "gemini_model" in ai_config:
                self._data.setdefault("api_keys", {})["gemini_model"] = ai_config["gemini_model"]
            if "deep_think_model" in ai_config:
                self._data.setdefault("api_keys", {})["deep_think_model"] = ai_config["deep_think_model"]
            if "quick_think_model" in ai_config:
                self._data.setdefault("api_keys", {})["quick_think_model"] = ai_config["quick_think_model"]
            self._save()

    # ── MT5 Settings ──────────────────────────────────────────────────────

    def get_mt5_symbol_suffix(self) -> str:
        with self._lock:
            return self._data.get("mt5", {}).get("symbol_suffix", "")

    def set_mt5_symbol_suffix(self, suffix: str) -> None:
        with self._lock:
            self._data.setdefault("mt5", {})["symbol_suffix"] = suffix
            self._save()

    # ── Trading Defaults ──────────────────────────────────────────────────

    def get_trading_defaults(self) -> dict:
        with self._lock:
            return dict(self._data.get("trading_defaults", {}))

    def set_trading_defaults(self, defaults: dict) -> None:
        with self._lock:
            self._data.setdefault("trading_defaults", {}).update(defaults)
            self._save()

    # ── Server ────────────────────────────────────────────────────────────

    def get_server_config(self) -> dict:
        with self._lock:
            return dict(self._data.get("server", {}))

    # ── Full Config Snapshot (for /setup/status debug) ────────────────────

    def get_full_config(self) -> dict:
        """Return the full config with passwords masked."""
        with self._lock:
            snapshot = json.loads(json.dumps(self._data, default=str))
            # Mask account passwords
            for acct in snapshot.get("accounts", []):
                if acct.get("mt5_password"):
                    acct["mt5_password"] = "••••••••"
            # Mask API keys
            for k, v in snapshot.get("api_keys", {}).items():
                if v and isinstance(v, str) and len(v) > 8 and "model" not in k:
                    snapshot["api_keys"][k] = v[:4] + "•" * (len(v) - 8) + v[-4:]
            # Mask database URL password portion
            db_url = snapshot.get("database", {}).get("url", "")
            if db_url and "@" in db_url:
                # Mask the password in the connection string
                parts = db_url.split("@")
                pre_at = parts[0]
                if ":" in pre_at:
                    user_part = pre_at.rsplit(":", 1)[0]
                    snapshot["database"]["url"] = f"{user_part}:••••••••@{'@'.join(parts[1:])}"
            return snapshot

    # ── .env Auto-Migration ───────────────────────────────────────────────

    def _try_env_migration(self) -> None:
        """
        If .env exists in the backend dir, migrate its values into config.json.
        This provides backward compatibility for existing deployments.
        """
        env_paths = [
            Path("/app/backend/.env"),
            Path(__file__).parent / ".env",
        ]
        env_path = None
        for p in env_paths:
            if p.exists():
                env_path = p
                break

        if not env_path:
            return

        logger.info(f"[ConfigManager] Found .env at {env_path} — migrating...")

        env_vars = {}
        try:
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and value:
                            env_vars[key] = value
        except OSError as exc:
            logger.error(f"[ConfigManager] Failed to read .env: {exc}")
            return

        with self._lock:
            # Database
            if env_vars.get("DATABASE_URL"):
                self._data.setdefault("database", {})["url"] = env_vars["DATABASE_URL"]

            # API keys
            if env_vars.get("GEMINI_API_KEY"):
                self._data.setdefault("api_keys", {})["gemini_api_key"] = env_vars["GEMINI_API_KEY"]
            if env_vars.get("GEMINI_MODEL"):
                self._data.setdefault("api_keys", {})["gemini_model"] = env_vars["GEMINI_MODEL"]
            if env_vars.get("DEEP_THINK_MODEL"):
                self._data.setdefault("api_keys", {})["deep_think_model"] = env_vars["DEEP_THINK_MODEL"]
            if env_vars.get("QUICK_THINK_MODEL"):
                self._data.setdefault("api_keys", {})["quick_think_model"] = env_vars["QUICK_THINK_MODEL"]
            if env_vars.get("ALPACA_NEWS_API_KEY"):
                self._data.setdefault("api_keys", {})["alpaca_news_api_key"] = env_vars["ALPACA_NEWS_API_KEY"]

            # MT5 account
            mt5_login = env_vars.get("MT5_LOGIN")
            mt5_password = env_vars.get("MT5_PASSWORD")
            mt5_server = env_vars.get("MT5_SERVER")
            if mt5_login and mt5_login != "0":
                account_id = self.add_account({
                    "label": f"{mt5_server or 'Default'} Account",
                    "mt5_login": mt5_login,
                    "mt5_password": mt5_password or "",
                    "mt5_server": mt5_server or "",
                    "is_default": True,
                })
                logger.info(f"[ConfigManager] Migrated MT5 account: {account_id}")

            # MT5 settings
            if env_vars.get("MT5_SYMBOL_SUFFIX"):
                self._data.setdefault("mt5", {})["symbol_suffix"] = env_vars["MT5_SYMBOL_SUFFIX"]

            # Ollama
            if env_vars.get("OLLAMA_BASE_URL"):
                self._data.setdefault("ollama", {})["base_url"] = env_vars["OLLAMA_BASE_URL"]
            if env_vars.get("OLLAMA_MODEL"):
                self._data.setdefault("ollama", {})["model"] = env_vars["OLLAMA_MODEL"]
            if env_vars.get("OLLAMA_MODEL_NAME"):
                self._data.setdefault("ollama", {})["model_name"] = env_vars["OLLAMA_MODEL_NAME"]

            # AI Brain
            if env_vars.get("AI_BRAIN_ENABLED"):
                self._data.setdefault("ai_brain", {})["enabled"] = (
                    env_vars["AI_BRAIN_ENABLED"].lower() == "true"
                )
            if env_vars.get("AI_ANALYSIS_INTERVAL_MINUTES"):
                self._data.setdefault("ai_brain", {})["analysis_interval_minutes"] = int(
                    env_vars["AI_ANALYSIS_INTERVAL_MINUTES"]
                )

            # Trading defaults
            defaults = {}
            if env_vars.get("DEFAULT_SYMBOL"):
                defaults["symbol"] = env_vars["DEFAULT_SYMBOL"]
            if env_vars.get("DEFAULT_QTY"):
                defaults["qty"] = float(env_vars["DEFAULT_QTY"])
            if env_vars.get("DEFAULT_STOP_LOSS_PCT"):
                defaults["stop_loss_pct"] = float(env_vars["DEFAULT_STOP_LOSS_PCT"])
            if env_vars.get("DEFAULT_BB_PERIOD"):
                defaults["bb_period"] = int(env_vars["DEFAULT_BB_PERIOD"])
            if env_vars.get("DEFAULT_BB_STD_DEV"):
                defaults["bb_std_dev"] = float(env_vars["DEFAULT_BB_STD_DEV"])
            if env_vars.get("MAX_DAILY_DRAWDOWN_PCT"):
                defaults["max_daily_drawdown_pct"] = float(env_vars["MAX_DAILY_DRAWDOWN_PCT"])
            if defaults:
                self._data.setdefault("trading_defaults", {}).update(defaults)

            # Server
            if env_vars.get("HOST"):
                self._data.setdefault("server", {})["host"] = env_vars["HOST"]
            if env_vars.get("PORT"):
                self._data.setdefault("server", {})["port"] = int(env_vars["PORT"])

            # Mark migrated setups as complete
            self._data["setup_complete"] = True
            self._save()

        logger.info("[ConfigManager] .env migration complete — setup_complete=True")


# ── Singleton ──────────────────────────────────────────────────────────────
config_manager = ConfigManager()
