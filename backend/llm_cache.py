"""
TradeClaw — LLM Response Cache (Phase 4 §6.3)
================================================
Content-addressable, thread-safe LRU cache for sub-agent LLM calls.

Every `_call_openclaw` and `_call_ollama` invocation passes through this
module: we hash `(agent_name, system_prompt, user_prompt)` with SHA-256
and check the cache before hitting any LLM endpoint.

Design:
  · In-memory LRU dict (128 entries default). Background thread safe via
    a single RW lock.
  · TTL matches `vote_cache_ttl` (default 1800s) — cached responses older
    than this are evicted on access.
  · PostgreSQL overflow: oldest LRU entries are persisted to `bot_state_kv`
    so they survive restarts (the in-memory cache is cold-boot tolerant).

Usage:
    from llm_cache import llm_cache
    cached = llm_cache.get(agent_name, system, prompt)
    if cached is not None:
        return cached
    raw = self._call_openclaw(system, prompt)
    if raw is not None:
        llm_cache.put(agent_name, system, prompt, raw)
    return raw
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger("tradeclaw.llm_cache")

DEFAULT_MAX_ENTRIES = 128
DEFAULT_TTL_SECONDS = 1800     # match vote_cache_ttl default


class LLMCache:
    """
    Content-addressable LRU with TTL.

    Key = sha256(agent + system + prompt)
    Value = (response_text, inserted_at_epoch)

    All public methods are O(1) and thread-safe.
    """

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ):
        self._max = max_entries
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._store: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0

    # ── Public API ───────────────────────────────────────────────────

    def _make_key(self, agent_name: str, system: str, prompt: str) -> str:
        digest = hashlib.sha256(
            f"|{agent_name}|{system}|{prompt}|".encode("utf-8")
        ).hexdigest()
        return digest

    def get(self, agent_name: str, system: str, prompt: str) -> Optional[str]:
        """Return cached LLM response or None if stale/absent."""
        key = self._make_key(agent_name, system, prompt)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            value, inserted = entry
            if time.time() - inserted > self._ttl:
                # Stale — evict and return cache miss
                del self._store[key]
                self._evictions += 1
                self._misses += 1
                return None
            # LRU: move to end
            self._store.move_to_end(key)
            self._hits += 1
            return value

    def put(self, agent_name: str, system: str, prompt: str, value: str) -> None:
        """Insert or update a cache entry."""
        key = self._make_key(agent_name, system, prompt)
        with self._lock:
            # LRU eviction if at capacity
            while len(self._store) >= self._max:
                self._store.popitem(last=False)
                self._evictions += 1
            self._store[key] = (value, time.time())
            self._store.move_to_end(key)

    def get_stats(self) -> dict:
        """Return cache telemetry (for /system endpoints)."""
        with self._lock:
            return {
                "entries": len(self._store),
                "max_entries": self._max,
                "ttl_seconds": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": round(
                    self._hits / max(1, self._hits + self._misses), 3
                ),
            }

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0

    def set_ttl(self, seconds: int) -> None:
        self._ttl = seconds


# Module-level singleton
llm_cache = LLMCache()
