"""
TradeClaw — Firebase Persistence Layer
=======================================
All async wrappers for Firestore operations.
Handles bot configs, trades, equity, AI decisions, fleet config,
live telemetry, and vector-store-style strategy context retrieval.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Any

import firebase_admin
from firebase_admin import credentials
from google.cloud.firestore_v1.async_client import AsyncClient as AsyncFirestore
from google.cloud.firestore_v1 import Query as FirestoreQuery
from google.cloud.firestore_v1.base_query import FieldFilter
import google.auth

logger = logging.getLogger("tradeclaw.firebase_store")

# ─────────────────────────────────────────────
# FIREBASE INIT
# ─────────────────────────────────────────────

_app: Optional[firebase_admin.App] = None
_firestore: Optional[AsyncFirestore] = None
_google_creds = None   # raw google.auth credentials (for Firestore async client)


def init_firebase(service_account_path: Optional[str] = None):
    """
    Initialize Firebase Admin SDK + a direct Firestore AsyncClient.

    firebase-admin 6.x dropped `firestore.async_client()`. We instead build the
    AsyncClient directly from the same credentials, which works across all versions.
    """
    global _app, _firestore, _google_creds

    if _app:
        return  # Already initialised

    options = {}

    try:
        if service_account_path:
            # Service account: works both for firebase-admin AND google-cloud-firestore
            cred = credentials.Certificate(service_account_path)
            _app = firebase_admin.initialize_app(cred, options)
            logger.info(f"Firebase initialized with service account: {service_account_path}")

            # Build google.oauth2 credentials from the same JSON for AsyncClient
            from google.oauth2 import service_account as _sa
            _google_creds = _sa.Credentials.from_service_account_file(
                service_account_path,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            project_id = cred.project_id
        else:
            # Application Default Credentials fallback
            cred = credentials.ApplicationDefault()
            _app = firebase_admin.initialize_app(cred, options)
            logger.info("Firebase initialized with Application Default Credentials")
            _google_creds, project_id = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )

        # Build the async Firestore client directly — avoids broken async_client() call
        _firestore = AsyncFirestore(
            project=project_id,
            credentials=_google_creds,
        )
        logger.info(f"Firestore async client ready (project={project_id})")

    except Exception as e:
        logger.error(f"Firebase initialization failed: {e}")
        raise


def get_firestore() -> AsyncFirestore:
    if _firestore is None:
        raise RuntimeError("Firebase not initialized. Call init_firebase() first.")
    return _firestore


def is_initialized() -> bool:
    return _app is not None


# ─────────────────────────────────────────────
# FLEET CONFIG
# ─────────────────────────────────────────────

async def save_fleet_config(config_dict: dict):
    """Persist FleetConfig to Firestore at fleet/config."""
    db = get_firestore()
    ref = db.collection("fleet").document("config")
    await ref.set({**config_dict, "updated_at": datetime.now(timezone.utc).isoformat()})
    logger.info("Fleet config saved to Firestore")


async def load_fleet_config() -> Optional[dict]:
    """Load FleetConfig from Firestore. Returns None if not found."""
    db = get_firestore()
    ref = db.collection("fleet").document("config")
    doc = await ref.get()
    if doc.exists:
        return doc.to_dict()
    return None


# ─────────────────────────────────────────────
# DARWINIAN WEIGHTS  (per-bot)
# ─────────────────────────────────────────────

async def save_darwinian_weights(bot_id: str, weights: dict):
    """Persist per-bot Darwinian agent weights at bots/{bot_id}/meta/darwinian_weights."""
    db = get_firestore()
    ref = db.collection("bots").document(bot_id).collection("meta").document("darwinian_weights")
    await ref.set({**weights, "updated_at": datetime.now(timezone.utc).isoformat()})
    logger.debug(f"[{bot_id}] Darwinian weights saved to Firestore")


async def load_darwinian_weights(bot_id: str) -> Optional[dict]:
    """Load per-bot Darwinian agent weights from Firestore."""
    db = get_firestore()
    ref = db.collection("bots").document(bot_id).collection("meta").document("darwinian_weights")
    doc = await ref.get()
    if doc.exists:
        data = doc.to_dict()
        return {k: v for k, v in data.items() if k not in ("updated_at",)}
    return None


# ─────────────────────────────────────────────
# AGENT RECOMMENDATIONS  (Sharpe attribution for Phase 4 autoresearch)
# ─────────────────────────────────────────────

async def log_agent_recommendation(
    bot_id: str,
    agent_name: str,
    symbol: str,
    direction: str,
    confidence: float,
    signal_price: float,
    timestamp: str,
) -> None:
    """
    Store one agent vote for later Sharpe attribution.
    Keyed at bots/{bot_id}/agent_recommendations/{timestamp}_{agent}.
    """
    db = get_firestore()
    doc_id = f"{timestamp}_{agent_name}".replace(":", "-").replace("+", "p")[:128]
    ref = (
        db.collection("bots").document(bot_id)
        .collection("agent_recommendations").document(doc_id)
    )
    await ref.set({
        "agent": agent_name,
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "signal_price": signal_price,
        "timestamp": timestamp,
        "scored": False,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    })


async def update_agent_recommendation_outcome(
    bot_id: str,
    agent_name: str,
    timestamp: str,
    forward_return_1d: float,
    forward_return_5d: float,
) -> None:
    """Score a previously logged recommendation against forward returns."""
    db = get_firestore()
    doc_id = f"{timestamp}_{agent_name}".replace(":", "-").replace("+", "p")[:128]
    ref = (
        db.collection("bots").document(bot_id)
        .collection("agent_recommendations").document(doc_id)
    )
    await ref.set({
        "forward_return_1d": forward_return_1d,
        "forward_return_5d": forward_return_5d,
        "scored": True,
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }, merge=True)


async def get_agent_sharpe(bot_id: str, agent_name: str, lookback_days: int = 60) -> Optional[float]:
    """
    Compute rolling Sharpe ratio for one agent's scored recommendations.
    Returns None when fewer than 3 scored records exist (insufficient data).
    """
    import numpy as np
    from datetime import timedelta

    db = get_firestore()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

    ref = (
        db.collection("bots").document(bot_id)
        .collection("agent_recommendations")
        .where(filter=FieldFilter("agent", "==", agent_name))
        .where(filter=FieldFilter("scored", "==", True))
        .where(filter=FieldFilter("timestamp", ">=", cutoff))
        .limit(200)
    )

    returns: list[float] = []
    async for doc in ref.stream():
        data = doc.to_dict()
        direction = data.get("direction", "HOLD")
        fwd = data.get("forward_return_1d", 0.0)
        confidence = data.get("confidence", 0.5)
        if direction == "BUY":
            signed = fwd * confidence
        elif direction == "SELL":
            signed = -fwd * confidence
        else:
            signed = 0.0
        returns.append(signed)

    if len(returns) < 3:
        return None

    mean_r = float(np.mean(returns))
    std_r = float(np.std(returns))
    return mean_r / std_r if std_r > 0 else 0.0


# ─────────────────────────────────────────────
# BOT CONFIG
# ─────────────────────────────────────────────

async def save_bot_config(bot_id: str, config_dict: dict):
    """Persist a BotConfig to Firestore at bots/{bot_id}/meta/config.

    Also writes a lightweight marker document at bots/{bot_id} so that
    list_bot_ids() can discover it — Firestore subcollection writes do NOT
    create the parent document automatically.
    """
    db = get_firestore()
    now = datetime.now(timezone.utc).isoformat()

    # 1. Write the full config to the subcollection
    ref = db.collection("bots").document(bot_id).collection("meta").document("config")
    await ref.set({**config_dict, "saved_at": now})

    # 2. Write a discoverable marker at the parent so list_bot_ids() works
    parent_ref = db.collection("bots").document(bot_id)
    await parent_ref.set(
        {
            "bot_id": bot_id,
            "name": config_dict.get("name", ""),
            "symbol": config_dict.get("symbol", ""),
            "created_at": config_dict.get("created_at", now),
            "updated_at": now,
        },
        merge=True,
    )
    logger.info(f"[{bot_id}] Bot config saved to Firestore")


async def update_bot_config(bot_id: str, updates: dict):
    """Merge partial config updates into an existing bot's Firestore config."""
    db = get_firestore()
    now = datetime.now(timezone.utc).isoformat()

    ref = db.collection("bots").document(bot_id).collection("meta").document("config")
    await ref.set({**updates, "updated_at": now}, merge=True)

    # Update the parent marker with the timestamp
    parent_ref = db.collection("bots").document(bot_id)
    await parent_ref.set({"updated_at": now}, merge=True)

    logger.info(f"[{bot_id}] Bot config updated in Firestore: {list(updates.keys())}")


async def load_bot_config(bot_id: str) -> Optional[dict]:
    """Load BotConfig from Firestore."""
    db = get_firestore()
    ref = db.collection("bots").document(bot_id).collection("meta").document("config")
    doc = await ref.get()
    if doc.exists:
        return doc.to_dict()
    return None


async def list_bot_ids() -> list[str]:
    """List all bot IDs that have been registered in Firestore."""
    db = get_firestore()
    docs = db.collection("bots").stream()
    return [doc.id async for doc in docs]


async def delete_bot_config(bot_id: str):
    """Remove a bot's config and its parent marker document."""
    db = get_firestore()
    # Delete the config subcollection doc
    await db.collection("bots").document(bot_id).collection("meta").document("config").delete()
    # Delete the parent marker so list_bot_ids no longer discovers this bot
    await db.collection("bots").document(bot_id).delete()
    logger.info(f"[{bot_id}] Bot config deleted from Firestore")


async def discover_orphaned_bot_ids(known_ids: set[str]) -> list[str]:
    """
    Migration helper: find bot configs that exist at bots/{id}/meta/config
    but have no parent marker document at bots/{id} (i.e. they were saved
    before the parent-marker fix and are invisible to list_bot_ids).

    Uses a collection-group query on 'meta' to find all config subcollection
    documents, then returns any bot_ids not already in `known_ids`.
    """
    db = get_firestore()
    orphans = []
    try:
        # Collection group query: find all documents in any 'meta' subcollection
        meta_docs = db.collection_group("meta").stream()
        async for doc in meta_docs:
            # doc.reference.path is like: bots/{bot_id}/meta/config
            parts = doc.reference.path.split("/")
            if len(parts) >= 4 and parts[0] == "bots" and parts[2] == "meta":
                bot_id = parts[1]
                if bot_id not in known_ids:
                    orphans.append(bot_id)
    except Exception as e:
        logger.warning(f"Collection group query on 'meta' failed: {e}")
        # Fallback: try to load a few known bot-id patterns (best effort)
    return orphans


# ─────────────────────────────────────────────
# TRADES
# ─────────────────────────────────────────────

async def save_trade(bot_id: str, trade: dict):
    """Persist a trade to Firestore at bots/{bot_id}/trades/{auto-id}."""
    db = get_firestore()
    trade_data = {
        **trade,
        "bot_id": bot_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    ref = db.collection("bots").document(bot_id).collection("trades")
    await ref.add(trade_data)


async def get_trades(bot_id: str, limit: int = 100) -> list[dict]:
    """Retrieve recent trades for a bot, ordered by timestamp descending."""
    db = get_firestore()
    ref = (
        db.collection("bots")
        .document(bot_id)
        .collection("trades")
        .order_by("timestamp", direction=FirestoreQuery.DESCENDING)
        .limit(limit)
    )
    docs = ref.stream()
    return [doc.to_dict() async for doc in docs]


# ─────────────────────────────────────────────
# EQUITY SNAPSHOTS
# ─────────────────────────────────────────────

async def save_equity_snapshot(bot_id: str, snapshot: dict):
    """Persist an equity snapshot to Firestore."""
    db = get_firestore()
    data = {**snapshot, "bot_id": bot_id, "saved_at": datetime.now(timezone.utc).isoformat()}
    await db.collection("bots").document(bot_id).collection("equity").add(data)


async def get_equity_history(bot_id: str, limit: int = 200) -> list[dict]:
    """Retrieve equity history for a bot."""
    db = get_firestore()
    ref = (
        db.collection("bots")
        .document(bot_id)
        .collection("equity")
        .order_by("timestamp", direction=FirestoreQuery.ASCENDING)
        .limit(limit)
    )
    docs = ref.stream()
    return [doc.to_dict() async for doc in docs]


# ─────────────────────────────────────────────
# AI DECISIONS
# ─────────────────────────────────────────────

async def save_ai_decision(bot_id: str, decision: dict):
    """Persist an AI Brain decision to Firestore."""
    db = get_firestore()
    data = {**decision, "bot_id": bot_id, "saved_at": datetime.now(timezone.utc).isoformat()}
    await db.collection("bots").document(bot_id).collection("ai_decisions").add(data)


async def get_ai_decisions(bot_id: str, limit: int = 50) -> list[dict]:
    """Retrieve recent AI decisions for a bot."""
    db = get_firestore()
    ref = (
        db.collection("bots")
        .document(bot_id)
        .collection("ai_decisions")
        .order_by("timestamp", direction=FirestoreQuery.DESCENDING)
        .limit(limit)
    )
    docs = ref.stream()
    return [doc.to_dict() async for doc in docs]


# ─────────────────────────────────────────────
# SUB-AGENT SIGNALS
# ─────────────────────────────────────────────

async def save_agent_signals(bot_id: str, signals: dict):
    """Persist a snapshot of sub-agent signals to Firestore."""
    db = get_firestore()
    data = {
        "bot_id": bot_id,
        "signals": {k: v if isinstance(v, dict) else vars(v) for k, v in signals.items()},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await db.collection("bots").document(bot_id).collection("agent_signals").add(data)


async def get_latest_agent_signals(bot_id: str) -> Optional[dict]:
    """Get the most recent agent signals snapshot for a bot."""
    db = get_firestore()
    ref = (
        db.collection("bots")
        .document(bot_id)
        .collection("agent_signals")
        .order_by("timestamp", direction=FirestoreQuery.DESCENDING)
        .limit(1)
    )
    docs = ref.stream()
    async for doc in docs:
        return doc.to_dict()
    return None


# ─────────────────────────────────────────────
# LIVE TELEMETRY — FIRESTORE
# ─────────────────────────────────────────────

async def push_live_telemetry(bot_id: str, state: dict):
    """
    Push live bot state to Firestore at live_telemetry/{bot_id}.
    Uses merge=True so partial updates don't wipe existing fields.
    """
    try:
        db = get_firestore()
        safe_state = {k: v for k, v in state.items() if _is_firestore_safe(v)}
        ref = db.collection("live_telemetry").document(bot_id)
        await ref.set(
            {**safe_state, "updated_at": datetime.now(timezone.utc).isoformat()},
            merge=True,
        )
    except Exception as e:
        logger.warning(f"[{bot_id}] Firestore telemetry push failed: {e}")


async def push_fleet_telemetry(fleet_snapshot: dict):
    """Push fleet-wide summary to live_telemetry/fleet in Firestore."""
    try:
        db = get_firestore()
        safe_snap = {k: v for k, v in fleet_snapshot.items() if _is_firestore_safe(v)}
        ref = db.collection("live_telemetry").document("fleet")
        await ref.set(
            {**safe_snap, "updated_at": datetime.now(timezone.utc).isoformat()},
            merge=True,
        )
    except Exception as e:
        logger.warning(f"Fleet Firestore telemetry push failed: {e}")


def _is_firestore_safe(value: Any) -> bool:
    """Filter values that Firestore can store (no None, no complex objects)."""
    return isinstance(value, (str, int, float, bool, list, dict))


# ─────────────────────────────────────────────
# STRATEGY CONTEXT — VECTOR STORE (RAG)
# ─────────────────────────────────────────────

async def save_strategy_context(bot_id: str, context: dict, embedding_text: str):
    """
    Save a strategy decision context with its embedding text for RAG retrieval.
    Stored at strategy_embeddings/{auto-id}.
    
    Note: True vector search requires Firestore's vector search feature (Spark tier
    supports manual cosine similarity via client-side filtering). For now, we store
    contexts and retrieve the most recent N for the AI to reason over — a simple but
    effective RAG pattern without requiring a paid vector DB.
    """
    db = get_firestore()
    data = {
        "bot_id": bot_id,
        "context": context,
        "embedding_text": embedding_text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await db.collection("strategy_embeddings").add(data)


async def retrieve_recent_strategy_contexts(
    bot_id: str, limit: int = 5
) -> list[dict]:
    """
    Retrieve recent strategy contexts for the bot (used as RAG memory in AI Brain prompts).
    Returns the most recent `limit` decisions with their reasoning.
    """
    db = get_firestore()
    ref = (
        db.collection("strategy_embeddings")
        .where(filter=FieldFilter("bot_id", "==", bot_id))
        .order_by("timestamp", direction=FirestoreQuery.DESCENDING)
        .limit(limit)
    )
    docs = ref.stream()
    results = []
    async for doc in docs:
        results.append(doc.to_dict())
    return list(reversed(results))  # Chronological order for AI prompt


# ─────────────────────────────────────────────
# BOT STATE (Key-Value)
# ─────────────────────────────────────────────

async def set_bot_state(bot_id: str, key: str, value: str):
    """Persist a key-value state pair for a bot in Firestore."""
    db = get_firestore()
    ref = db.collection("bots").document(bot_id).collection("state").document(key)
    await ref.set({
        "value": value,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


async def get_bot_state(bot_id: str, key: str) -> Optional[str]:
    """Retrieve a key-value state pair for a bot from Firestore."""
    db = get_firestore()
    ref = db.collection("bots").document(bot_id).collection("state").document(key)
    doc = await ref.get()
    if doc.exists:
        return doc.to_dict().get("value")
    return None


# ─────────────────────────────────────────────
# AGENT RECOMMENDATION TRACKING (For Autoresearch)
# ─────────────────────────────────────────────

async def log_agent_recommendation(
    bot_id: str,
    agent_name: str,
    symbol: str,
    direction: str,      # "BUY" | "SELL" | "HOLD"
    confidence: float,
    signal_price: float,
    timestamp: str,
):
    """Store one agent vote for later Sharpe attribution."""
    db = get_firestore()
    # document path: bots/{bot_id}/agent_recommendations/{timestamp}_{agent}
    # Sanitize ID
    doc_id = f"{timestamp}_{agent_name}".replace(":", "-").replace("+", "p").replace("/", "-")
    ref = db.collection("bots").document(bot_id).collection("agent_recommendations").document(doc_id)
    
    data = {
        "bot_id": bot_id,
        "agent": agent_name,
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "signal_price": signal_price,
        "timestamp": timestamp,
        "forward_return_1d": None,
        "forward_return_5d": None,
        "outcome_scored": False,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    await ref.set(data)


async def update_agent_recommendation_outcome(
    bot_id: str,
    agent_name: str,
    timestamp: str,
    forward_return_1d: float,
    forward_return_5d: float,
):
    """Called after 1d and 5d to score the prediction."""
    db = get_firestore()
    doc_id = f"{timestamp}_{agent_name}".replace(":", "-").replace("+", "p").replace("/", "-")
    ref = db.collection("bots").document(bot_id).collection("agent_recommendations").document(doc_id)
    
    await ref.update({
        "forward_return_1d": forward_return_1d,
        "forward_return_5d": forward_return_5d,
        "outcome_scored": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


async def get_agent_sharpe(bot_id: str, agent_name: str, lookback_days: int = 60) -> float:
    """Compute rolling Sharpe for one agent's recommendations."""
    import numpy as np
    db = get_firestore()
    
    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    
    # Note: Composite index might be needed for this query in production
    ref = (
        db.collection("bots")
        .document(bot_id)
        .collection("agent_recommendations")
        .where(filter=FieldFilter("agent", "==", agent_name))
        .where(filter=FieldFilter("outcome_scored", "==", True))
        .where(filter=FieldFilter("timestamp", ">=", since))
    )
    
    returns = []
    async for doc in ref.stream():
        data = doc.to_dict()
        # Use 5d return if available, fallback to 1d
        ret = data.get("forward_return_5d")
        if ret is None:
            ret = data.get("forward_return_1d")
            
        if ret is not None:
            # Attribution logic: 
            # If agent said BUY and return was positive, score is positive.
            # If agent said SELL and return was negative, score is positive.
            dir_str = data.get("direction", "HOLD")
            multiplier = 0.0
            if dir_str == "BUY": multiplier = 1.0
            elif dir_str == "SELL": multiplier = -1.0
            
            returns.append(ret * multiplier)
            
    if len(returns) < 5:
        return 0.0
        
    mean_r = float(np.mean(returns))
    std_r = float(np.std(returns))
    
    return (mean_r / std_r) if std_r > 0 else 0.0


# ─────────────────────────────────────────────
# DAILY TRADE STATS (Firestore)
# ─────────────────────────────────────────────

async def get_daily_pnl_sum(bot_id: str) -> float:
    """Sum realized PnL for today's trades from Firestore."""
    from datetime import date as _date
    db = get_firestore()
    today = _date.today().isoformat()
    ref = (
        db.collection("bots")
        .document(bot_id)
        .collection("trades")
        .where(filter=FieldFilter("trade_date", "==", today))
    )
    total_pnl = 0.0
    async for doc in ref.stream():
        trade = doc.to_dict()
        total_pnl += trade.get("pnl", 0.0)
    return total_pnl


async def get_trade_stats_today(bot_id: str) -> dict:
    """Get trade statistics for today from Firestore."""
    from datetime import date as _date
    db = get_firestore()
    today = _date.today().isoformat()
    ref = (
        db.collection("bots")
        .document(bot_id)
        .collection("trades")
        .where(filter=FieldFilter("trade_date", "==", today))
    )
    total = 0
    wins = 0
    async for doc in ref.stream():
        trade = doc.to_dict()
        total += 1
        if trade.get("pnl", 0.0) > 0:
            wins += 1
    return {
        "total_trades": total,
        "win_rate": (wins / total * 100) if total > 0 else 0.0,
    }


async def get_all_trades_firestore(bot_id: str, limit: int = 200) -> list[dict]:
    """Get recent trades for a specific bot from Firestore."""
    return await get_trades(bot_id, limit=limit)


# ─────────────────────────────────────────────
# MARKET BARS — Persistent Per-Symbol Bar Store
# ─────────────────────────────────────────────
# Stores 1-minute OHLC bars in Firestore so bots can load 1000+ bars
# on startup instead of being limited to MT5's 100-bar warmup window.
# Bars are per-symbol (not per-bot) — multiple bots trading the same
# symbol share the same bar history.
#
# Collection: market_bars/{symbol_key}/bars/{timestamp_iso}
# ─────────────────────────────────────────────


def symbol_to_key(symbol: str) -> str:
    """
    Normalize a trading symbol into a safe Firestore document path segment.
    Firestore doc IDs cannot contain '/'.

    Examples:
        "BTC/USD"  → "BTC-USD"
        "AAPL"     → "AAPL"
        "ETH/USDT" → "ETH-USDT"
    """
    return symbol.replace("/", "-").upper()


async def append_bar(symbol: str, bar: dict) -> None:
    """
    Write a single OHLC bar to Firestore.  Uses set() with the bar's
    timestamp as document ID, making the write idempotent — the same
    bar written twice simply overwrites the same document.

    Expected bar dict keys:
        t (str):  ISO timestamp
        o (float): open
        h (float): high
        l (float): low
        c (float): close
        v (float): volume
        src (str): "live" | "warmup"
    """
    try:
        db = get_firestore()
        key = symbol_to_key(symbol)
        ts = bar.get("t", "")
        if not ts:
            logger.warning(f"append_bar: bar missing 't' field for {symbol}")
            return

        # Use timestamp as doc ID for idempotent writes
        doc_id = ts.replace(":", "-").replace("+", "p")  # Firestore-safe ID
        ref = (
            db.collection("market_bars")
            .document(key)
            .collection("bars")
            .document(doc_id)
        )
        await ref.set(bar)
    except Exception as e:
        logger.warning(f"append_bar({symbol}): {e}")


async def append_bars_batch(symbol: str, bars: list[dict]) -> int:
    """
    Write multiple bars in a single Firestore batch (max 500 per batch).
    Returns the number of bars written.
    """
    if not bars:
        return 0
    try:
        db = get_firestore()
        key = symbol_to_key(symbol)
        col_ref = db.collection("market_bars").document(key).collection("bars")

        written = 0
        # Firestore batches are limited to 500 operations
        for chunk_start in range(0, len(bars), 490):
            chunk = bars[chunk_start : chunk_start + 490]
            batch = db.batch()
            for bar in chunk:
                ts = bar.get("t", "")
                if not ts:
                    continue
                doc_id = ts.replace(":", "-").replace("+", "p")
                batch.set(col_ref.document(doc_id), bar)
                written += 1
            await batch.commit()

        return written
    except Exception as e:
        logger.warning(f"append_bars_batch({symbol}): {e}")
        return 0


async def load_bars(symbol: str, limit: int = 1000) -> list[dict]:
    """
    Load the most recent `limit` bars for a symbol from Firestore.
    Returns bars in chronological order (oldest first).
    """
    try:
        db = get_firestore()
        key = symbol_to_key(symbol)
        ref = (
            db.collection("market_bars")
            .document(key)
            .collection("bars")
            .order_by("t", direction=FirestoreQuery.DESCENDING)
            .limit(limit)
        )
        docs = ref.stream()
        bars = [doc.to_dict() async for doc in docs]
        bars.reverse()  # Chronological order
        return bars
    except Exception as e:
        logger.warning(f"load_bars({symbol}): {e}")
        return []


async def prune_bars(symbol: str, keep: int = 1200) -> int:
    """
    Delete all bars older than the most recent `keep` bars.
    Returns the number of documents pruned.
    """
    try:
        db = get_firestore()
        key = symbol_to_key(symbol)

        # First, count how many bars exist by fetching all doc IDs
        # (only IDs to minimize read cost)
        col_ref = (
            db.collection("market_bars")
            .document(key)
            .collection("bars")
            .order_by("t", direction=FirestoreQuery.DESCENDING)
        )
        all_docs = []
        async for doc in col_ref.stream():
            all_docs.append(doc.reference)

        if len(all_docs) <= keep:
            return 0

        # Delete docs beyond the keep threshold
        to_delete = all_docs[keep:]
        pruned = 0
        for chunk_start in range(0, len(to_delete), 490):
            chunk = to_delete[chunk_start : chunk_start + 490]
            batch = db.batch()
            for ref in chunk:
                batch.delete(ref)
            await batch.commit()
            pruned += len(chunk)

        logger.info(f"prune_bars({symbol}): pruned {pruned} old bars (kept {keep})")
        return pruned
    except Exception as e:
        logger.warning(f"prune_bars({symbol}): {e}")
        return 0


# ─────────────────────────────────────────────
# MIGRATION SHIMS — init_db / insert_trade
# ─────────────────────────────────────────────
# These provide API-compatible wrappers so main.py can import from
# firebase_store instead of database.py with minimal refactoring.

async def init_db():
    """No-op — Firestore is schemaless. Kept for import compatibility."""
    logger.info("init_db() called — Firestore requires no schema init")


async def insert_trade_record(
    bot_id: str,
    timestamp: str,
    side: str,
    symbol: str,
    qty: int,
    price: float,
    pnl: float = 0.0,
    signal: str = "",
    params_snapshot: str = "",
    fib_level_triggered: Optional[str] = None,
) -> None:
    """Insert a trade record into Firestore (replaces database.insert_trade)."""
    from datetime import date as _date
    trade = {
        "timestamp": timestamp,
        "side": side,
        "symbol": symbol,
        "qty": qty,
        "price": price,
        "pnl": pnl,
        "signal": signal,
        "trade_date": _date.today().isoformat(),
        "params_snapshot": params_snapshot,
        "fib_level_triggered": fib_level_triggered,
    }
    await save_trade(bot_id, trade)


async def insert_equity_record(
    bot_id: str, timestamp: str, equity: float, daily_pnl: float = 0.0
) -> None:
    """Insert an equity snapshot into Firestore (replaces database.insert_equity_snapshot)."""
    snapshot = {
        "timestamp": timestamp,
        "equity": equity,
        "daily_pnl": daily_pnl,
    }
    await save_equity_snapshot(bot_id, snapshot)


# ─────────────────────────────────────────────
# LEGACY SHIMS (database.py drop-in replacements)
# ─────────────────────────────────────────────
# These functions match the exact signatures of the old database.py API
# so that main.py, ai_brain.py, and strategy.py can swap
# `from database import X` → `from firebase_store import X`
# with ZERO call-site changes.  They all route through the new
# bot-scoped Firestore functions using a fixed legacy bot ID.

LEGACY_BOT_ID = "legacy_engine"


async def insert_trade(
    timestamp: str,
    side: str,
    symbol: str,
    qty: int,
    price: float,
    pnl: float = 0.0,
    signal: str = "",
    params_snapshot: str = "",
    fib_level_triggered: Optional[str] = None,
) -> None:
    """Legacy shim — routes to Firestore save_trade."""
    await insert_trade_record(
        bot_id=LEGACY_BOT_ID,
        timestamp=timestamp,
        side=side,
        symbol=symbol,
        qty=qty,
        price=price,
        pnl=pnl,
        signal=signal,
        params_snapshot=params_snapshot,
        fib_level_triggered=fib_level_triggered,
    )


async def insert_equity_snapshot(
    timestamp: str, equity: float, daily_pnl: float = 0.0
) -> None:
    """Legacy shim — routes to Firestore save_equity_snapshot."""
    await insert_equity_record(
        bot_id=LEGACY_BOT_ID,
        timestamp=timestamp,
        equity=equity,
        daily_pnl=daily_pnl,
    )


async def get_all_trades(limit: int = 200) -> list[dict]:
    """Legacy shim — routes to Firestore get_trades."""
    return await get_trades(LEGACY_BOT_ID, limit=limit)


async def get_recent_trades_for_analysis(limit: int = 100) -> list[dict]:
    """Legacy shim — routes to Firestore get_trades."""
    return await get_trades(LEGACY_BOT_ID, limit=limit)


async def insert_ai_decision(
    timestamp: str,
    trigger: str,
    trades_analysed: int,
    win_rate_before: float,
    daily_pnl_before: float,
    params_before: str,
    params_after: str,
    reasoning: str,
    model_used: str,
    applied: int,
) -> None:
    """Legacy shim — routes to Firestore save_ai_decision."""
    decision = {
        "timestamp": timestamp,
        "trigger": trigger,
        "trades_analysed": trades_analysed,
        "win_rate_before": win_rate_before,
        "daily_pnl_before": daily_pnl_before,
        "params_before": params_before,
        "params_after": params_after,
        "reasoning": reasoning,
        "model_used": model_used,
        "applied": applied,
    }
    await save_ai_decision(LEGACY_BOT_ID, decision)


# Legacy-compatible wrappers for the remaining database.py functions
# that also need the bot_id parameter stripped.

async def _legacy_get_equity_history(limit: int = 500) -> list[dict]:
    """Legacy shim — routes to Firestore get_equity_history with LEGACY_BOT_ID."""
    return await get_equity_history(LEGACY_BOT_ID, limit=limit)


async def _legacy_get_daily_pnl_sum() -> float:
    """Legacy shim — routes to Firestore get_daily_pnl_sum with LEGACY_BOT_ID."""
    return await get_daily_pnl_sum(LEGACY_BOT_ID)


async def _legacy_get_trade_stats_today() -> dict:
    """Legacy shim — routes to Firestore get_trade_stats_today with LEGACY_BOT_ID."""
    return await get_trade_stats_today(LEGACY_BOT_ID)


async def _legacy_set_bot_state(key: str, value: str) -> None:
    """Legacy shim — routes to Firestore set_bot_state with LEGACY_BOT_ID."""
    await set_bot_state(LEGACY_BOT_ID, key, value)


async def _legacy_get_bot_state(key: str) -> Optional[str]:
    """Legacy shim — routes to Firestore get_bot_state with LEGACY_BOT_ID."""
    return await get_bot_state(LEGACY_BOT_ID, key)


async def _legacy_get_ai_decisions(limit: int = 50) -> list[dict]:
    """Legacy shim — routes to Firestore get_ai_decisions with LEGACY_BOT_ID."""
    return await get_ai_decisions(LEGACY_BOT_ID, limit=limit)



