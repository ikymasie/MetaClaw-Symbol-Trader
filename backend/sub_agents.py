"""
TradeClaw — Sub-Agent Framework (Multi-Agent System v2)
=========================================================
Each bot hosts a pool of six specialised expert agents.  They run in parallel
threads to gather market intelligence, then VOTE on whether to execute a trade
via the deliberate() quorum function before the Executioner fires any order.

Agent roster:
  · WatchmanAgent   — Market quality: bid-ask spread, volume spike detection
  · SentimentAgent  — News/social sentiment via OpenClaw + Google Search
  · MacroAgent      — VIX, yield curve, Fed language via OpenClaw
  · EarningsAgent   — Upcoming earnings risk via OpenClaw
  · TechnicalAgent  — Cross-timeframe TA via local Ollama (fast, offline)
  · RiskManagerAgent — Kelly Criterion gating: approves qty or issues VETO

Deliberation protocol:
  1. Any VETO from any agent → trade blocked
  2. Quorum of ≥ 3/5 voting agents (excl. RiskManager) must agree on direction
  3. Weighted vote score ≥ 0.2 required to proceed
  4. RiskManagerAgent runs last to approve qty if quorum passes
"""

import asyncio
import json
import logging
import queue as _stdlib_queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

import httpx
from openai import OpenAI
from mt5_hub import mt5_hub
from gemini_budget import gemini_budget
from prompt_loader import PromptLoader
from agent_schemas import (
    AgentSignalSchema,
    AgentVoteSchema,
    CROObjectionSchema,
    to_gemini_response_format,
)
from pydantic import BaseModel as _PydanticBaseModel
from llm_cache import llm_cache   # Phase 4 §6.3 — content-addressable LRU
from ollama_pool import get_ollama_model  # Phase 4 §6.4 — per-agent model selection

logger = logging.getLogger("tradeclaw.sub_agents")

# Standard correlation mappings for major assets
CORRELATION_MAP = {
    "EURUSD": ["GBPUSD", "DXY", "XAUUSD", "USDJPY"],
    "GBPUSD": ["EURUSD", "DXY", "XAUUSD"],
    "USDJPY": ["XAUUSD", "DXY", "US30", "EURUSD"],
    "XAUUSD": ["USDJPY", "DXY", "EURUSD", "US30"],
    "BTCUSD": ["ETHUSD", "US100", "US30", "DXY"],
    "ETHUSD": ["BTCUSD", "US100", "US30"],
    "US30": ["US100", "US500", "DXY", "USDJPY"],
    "US100": ["US500", "US30", "BTCUSD"],
    "US500": ["US100", "US30", "DXY"],
}

# Module-level flag: once we discover Ollama doesn't support /api/generate for
# a given model, mark it so every subsequent ephemeral agent skips the call
# without retrying.  Key = (base_url, model_name).
_ollama_generate_unsupported: set[tuple[str, str]] = set()

# Module-level reference to the main asyncio event loop.
# Set by main.py at startup so background threads can schedule async coroutines
# (e.g. PostgreSQL writes from DarwinianWeightStore).
_main_event_loop: Optional[asyncio.AbstractEventLoop] = None


def set_main_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Called once by main.py after the FastAPI lifespan initialises the loop."""
    global _main_event_loop
    _main_event_loop = loop


# ─────────────────────────────────────────────
# AGENT SIGNAL
# ─────────────────────────────────────────────

@dataclass
class AgentSignal:
    """Structured output from a sub-agent analysis run."""
    agent: str
    sentiment: float      # -1.0 (very bearish) to +1.0 (very bullish)
    confidence: float     # 0.0 to 1.0
    reasoning: str
    sources: list = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw_response: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def neutral(cls, agent: str, reason: str = "No data") -> "AgentSignal":
        """Return a neutral signal when analysis cannot be completed."""
        return cls(
            agent=agent,
            sentiment=0.0,
            confidence=0.0,
            reasoning=reason,
        )


# ─────────────────────────────────────────────
# AGENT VOTE (MAS deliberation protocol)
# ─────────────────────────────────────────────

@dataclass
class AgentVote:
    """
    Per-trade directional vote from a single sub-agent.
    Used by SubAgentPool.deliberate() to determine if a trade fires.
    """
    agent: str
    vote: str              # "BUY" | "SELL" | "HOLD" | "VETO"
    confidence: float      # 0.0 – 1.0
    reasoning: str
    weight: float = 1.0    # Agent-specific vote weight in quorum calculation
    darwinian_weight: float = 1.0  # performance-adjusted multiplier [0.3, 2.5]
    veto_reason: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TradeDecision:
    """
    Final output of SubAgentPool.deliberate().
    Consumed by bot_engine._live_tick() to decide whether to call ExecutionerAgent.
    """
    approved: bool
    signal: str                    # "BUY" | "SELL" | "HOLD"
    approved_qty: float            # Qty approved by RiskManagerAgent (0 if blocked)
    order_urgency: str             # "HIGH" | "LOW"
    quorum_score: float            # Weighted vote score (-1.0 – +1.0)
    votes: list = field(default_factory=list)   # list[AgentVote.to_dict()]
    veto_agents: list = field(default_factory=list)  # agents that issued VETO
    reasoning: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────
# BASE AGENT
# ─────────────────────────────────────────────

class BaseAgent:
    """Base class for all sub-agents."""

    AGENT_NAME = "base"
    TIMEOUT_SECONDS = 90  # Ollama on CPU needs ~40s

    def __init__(
        self,
        bot_id: str,
        symbol: str,
        openclaw_client: Optional[OpenAI],
        openclaw_model: str,
        ollama_base_url: str = "http://localhost:11434",
        ollama_model: str = "gemma4:e4b",
        market_trends: dict = None,
    ):
        self.bot_id = bot_id
        self.symbol = symbol
        self._openclaw_client = openclaw_client
        self._openclaw_model = openclaw_model
        self._ollama_base_url = ollama_base_url
        self._ollama_model = ollama_model
        self.market_trends = market_trends or {}
        # Phase 3 §9.1 — Optional in-process DataFrame injection. Populated
        # by SubAgentPool when MarketDataAggregator emits aggregated frames.
        # Keys: "1m", "15m", "1h", "1d", "1wk", "1mo". Values: pd.DataFrame
        # with OHLCV columns and a DatetimeIndex.
        self.dataframes: dict = {}
        self._logger = logging.getLogger(f"tradeclaw.agents.{self.AGENT_NAME}[{bot_id}]")

    def run(self) -> AgentSignal:
        raise NotImplementedError

    def _call_openclaw(
        self,
        system: str,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.3,
        include_search: bool = True,
        schema: Optional[type] = None,
    ) -> Optional[str]:
        """
        Call Gemini via OpenAI-compatible endpoint (budget-gated).

        Phase 2 (§6.2) Structured Output:
        ---------------------------------
        If `schema` (a Pydantic `BaseModel` subclass) is provided, this method
        will attempt to bind it via Gemini's `response_format={"type":
        "json_schema", ...}` payload so the model is *forced* to emit
        conforming JSON. On any failure (bad-request, schema-unsupported
        model, network error), it falls back to plain
        `response_format={"type": "json_object"}` and retries once.

        Callers should always re-validate the returned text via the same
        Pydantic schema — see `_parse_signal_from_json` / `_parse_vote_from_json`.
        """
        if not self._openclaw_client:
            return None

        # ── Budget gate: skip Gemini if budget exhausted or circuit breaker active
        if not gemini_budget.can_call():
            self._logger.info("Gemini call skipped (budget exhausted) — use Ollama fallback")
            return None

        # Phase 4 §6.3 — content-addressable LLM response cache.
        # Check BEFORE making the API call; identical prompts within the
        # TTL window are served from in-memory LRU (zero latency).
        model = model or self._openclaw_model
        # Strip any prefix (e.g. "google/gemini-flash-latest" → "gemini-flash-latest")
        if "/" in model:
            model = model.split("/", 1)[1]
        # Phase 3 §6.1c — auto-downgrade to -lite variant when budget pressure ≥ 80%
        model = gemini_budget.get_recommended_model(model)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        # Phase 4 §6.3 — content-addressable LLM response cache.
        # Hash (agent + system + prompt) and check LRU before any API call.
        _cached = llm_cache.get(self.AGENT_NAME, system, prompt)
        if _cached is not None:
            # Cache hit — skip the API call entirely. The cached response
            # was written by a successful _call_openclaw/ollama path below.
            self._logger.debug(f"[{self.AGENT_NAME}] LLM cache hit — serving from memory")
            gemini_budget.record_call(model=model, tokens=len(_cached.split()))
            return _cached

        # Build initial response_format — prefer json_schema when a schema
        # is supplied so the model is forced to conform.
        use_schema = schema is not None and isinstance(schema, type) and issubclass(schema, _PydanticBaseModel)
        if use_schema:
            try:
                primary_rf = to_gemini_response_format(schema)
            except Exception as _se:
                self._logger.debug(f"Schema → JSON-Schema build failed ({_se}); using json_object")
                primary_rf = {"type": "json_object"}
                use_schema = False
        else:
            primary_rf = {"type": "json_object"}

        def _do_call(rf):
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 512,
                "response_format": rf,
            }
            return self._openclaw_client.chat.completions.create(**kwargs, timeout=30)

        def _extract_tokens(_resp) -> int:
            """Best-effort completion-token extraction for cost attribution."""
            try:
                usage = getattr(_resp, "usage", None)
                if usage is not None:
                    return int(getattr(usage, "completion_tokens", 0)) or 400
            except Exception:
                pass
            return 400

        try:
            resp = _do_call(primary_rf)
            gemini_budget.record_call(model=model, tokens=_extract_tokens(resp))
            _raw = resp.choices[0].message.content
            llm_cache.put(self.AGENT_NAME, system, prompt, _raw)
            return _raw
        except Exception as e:
            err_str = str(e)
            # 429 / quota → trip the circuit breaker; do not fall back.
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                gemini_budget.record_429()
                self._logger.warning(f"Gemini call failed (rate-limited): {e}")
                return None

            # If json_schema was rejected (400 / unsupported response_format),
            # retry once with the looser json_object mode.
            schema_related = use_schema and (
                "400" in err_str
                or "response_format" in err_str.lower()
                or "json_schema" in err_str.lower()
                or "schema" in err_str.lower()
            )
            if schema_related:
                self._logger.info(
                    "Gemini json_schema mode rejected — falling back to json_object: "
                    f"{err_str[:160]}",
                    extra={
                        "event": "llm_schema_fallback",
                        "agent": self.AGENT_NAME,
                        "model": model,
                        "reason": err_str[:120],
                    },
                )
                try:
                    resp = _do_call({"type": "json_object"})
                    gemini_budget.record_call(model=model, tokens=_extract_tokens(resp))
                    _raw2 = resp.choices[0].message.content
                    llm_cache.put(self.AGENT_NAME, system, prompt, _raw2)
                    return _raw2
                except Exception as e2:
                    err_str2 = str(e2)
                    if "429" in err_str2 or "RESOURCE_EXHAUSTED" in err_str2:
                        gemini_budget.record_429()
                    self._logger.warning(f"Gemini call failed (after fallback): {e2}")
                    return None

            self._logger.warning(f"Gemini call failed: {e}")
            return None

    def _call_ollama(self, prompt: str, system_hint: str = "") -> Optional[str]:
        """Call local Ollama via /api/generate.  Phase 4 §6.3 — checks LLM cache first."""
        key = (self._ollama_base_url, self._ollama_model)
        if key in _ollama_generate_unsupported:
            return None

        # Phase 4 §6.3 — content-addressable LLM cache
        _cached = llm_cache.get(self.AGENT_NAME, system_hint, prompt)
        if _cached is not None:
            self._logger.debug(f"[{self.AGENT_NAME}] Ollama cache hit — serving from memory")
            return _cached

        try:
            resp = httpx.post(
                f"{self._ollama_base_url}/api/generate",
                json={
                    "model": self._ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
                timeout=self.TIMEOUT_SECONDS,
            )
            if resp.status_code in (400, 404):
                body = resp.json() if resp.status_code == 400 else {}
                err = body.get("error", "Not Found")
                _ollama_generate_unsupported.add(key)
                self._logger.warning(
                    f"Ollama model {self._ollama_model!r} generate unavailable ({err}) "
                    f"— disabling Ollama for this session."
                )
                return None
            resp.raise_for_status()
            _raw = resp.json().get("response", "")
            if _raw:
                llm_cache.put(self.AGENT_NAME, system_hint, prompt, _raw)
            return _raw
        except Exception as e:
            self._logger.warning(f"Ollama call failed: {e}")
            return None

    @staticmethod
    def _extract_json(raw: str) -> dict:
        """Extract JSON from LLM output."""
        import re
        raw = raw.strip()
        try:
            return json.loads(raw)
        except Exception:
            pass
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"No JSON found in: {raw[:200]}")

    def _parse_signal_from_json(self, raw: str, agent_name: str) -> AgentSignal:
        """Parse a structured AgentSignal from LLM JSON output using AgentSignalSchema."""
        try:
            parsed_dict = self._extract_json(raw)
            # Validate via Pydantic
            validated = AgentSignalSchema(**parsed_dict)
            
            return AgentSignal(
                agent=agent_name,
                sentiment=validated.sentiment,
                confidence=validated.confidence,
                reasoning=validated.reasoning,
                sources=validated.sources,
                raw_response=raw[:500],
            )
        except Exception as e:
            self._logger.warning(f"Failed to parse signal JSON for {agent_name}: {e}")
            # Fallback to manual extraction if Pydantic fails
            try:
                parsed = self._extract_json(raw)
                sentiment = float(parsed.get("sentiment", 0.0))
                sentiment = max(-1.0, min(1.0, sentiment))
                confidence = float(parsed.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))
                return AgentSignal(
                    agent=agent_name,
                    sentiment=sentiment,
                    confidence=confidence,
                    reasoning=parsed.get("reasoning", "No reasoning provided."),
                    sources=parsed.get("sources", []),
                    raw_response=raw[:500],
                )
            except Exception:
                return AgentSignal.neutral(agent_name, f"Parse error: {e}")

    def _parse_vote_from_json(self, raw: str, agent_name: str) -> AgentVote:
        """Parse a structured AgentVote from LLM JSON output using AgentVoteSchema."""
        try:
            parsed_dict = self._extract_json(raw)
            # Normalise vote casing BEFORE Pydantic Literal validation.
            # LLMs occasionally emit lowercase / mixed-case ("buy", "Sell").
            if isinstance(parsed_dict, dict) and "vote" in parsed_dict:
                _v = parsed_dict["vote"]
                if isinstance(_v, str):
                    parsed_dict["vote"] = _v.strip().upper()
            validated = AgentVoteSchema(**parsed_dict)

            return AgentVote(
                agent=agent_name,
                vote=validated.vote,  # Already uppercase + Literal-validated
                confidence=validated.confidence,
                reasoning=validated.reasoning,
                veto_reason=validated.veto_reason,
            )
        except Exception as e:
            self._logger.warning(f"Failed to parse vote JSON for {agent_name}: {e}")
            # Fallback to manual extraction
            try:
                parsed = self._extract_json(raw)
                vote = str(parsed.get("vote", "HOLD")).strip().upper()
                if vote not in ("BUY", "SELL", "HOLD", "VETO"):
                    vote = "HOLD"
                return AgentVote(
                    agent=agent_name,
                    vote=vote,
                    confidence=float(parsed.get("confidence", 0.5)),
                    reasoning=parsed.get("reasoning", "No reasoning provided."),
                    veto_reason=parsed.get("veto_reason"),
                )
            except Exception:
                return AgentVote(
                    agent=agent_name,
                    vote="HOLD",
                    confidence=0.0,
                    reasoning=f"Parse error: {e}",
                )


# ─────────────────────────────────────────────
# SENTIMENT AGENT
# ─────────────────────────────────────────────

class SentimentAgent(BaseAgent):
    """
    Analyses news headlines, Reddit/social sentiment, and analyst commentary
    for the bot's symbol using OpenClaw with Google Search grounding.
    """

    AGENT_NAME = "sentiment"

    def run(self) -> AgentSignal:
        self._logger.info(f"SentimentAgent running for {self.symbol}")
        
        # 1. Get real-time headlines from MT5Hub buffer
        recent_news = mt5_hub.get_recent_news(self.symbol)
        
        system, user_tpl = PromptLoader.get_agent_prompts(self.AGENT_NAME)
        now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

        if recent_news:
            # 2a. Buffered headlines available — no external search needed
            news_text = "\n".join([
                f"- [{n['timestamp']}] {n['headline']}: {n['summary'][:150]}..."
                for n in recent_news
            ])
            prompt = user_tpl.replace("{symbol}", self.symbol).replace(
                "{news_text}", news_text
            ).replace("{now}", now_str)

            raw = self._call_ollama(prompt)
            if raw:
                return self._parse_signal_from_json(raw, self.AGENT_NAME)
            raw = self._call_openclaw(system, prompt, include_search=False, schema=AgentSignalSchema)
        else:
            # 2b. No buffered headlines — delegate search to OpenClaw
            self._logger.info(f"No buffered headlines for {self.symbol}. Using web search.")
            search_prompt = (
                f"Search for the latest news and analyst commentary about {self.symbol} "
                f"as of {now_str}. Then analyse the sentiment and respond with ONLY valid JSON "
                f"matching this schema: "
                f'{{ "sentiment": <float -1.0 to 1.0>, "confidence": <float 0.0 to 1.0>, '
                f'"reasoning": "<2-3 sentences>", "sources": ["<url-or-source>"] }}'
            )
            # Note: include_search=True grounding may be incompatible with json_schema mode;
            # the _call_openclaw fallback will downgrade to json_object on rejection.
            raw = self._call_openclaw(system, search_prompt, include_search=True, schema=AgentSignalSchema)

        if raw:
            return self._parse_signal_from_json(raw, self.AGENT_NAME)
        return AgentSignal.neutral(self.AGENT_NAME, "All LLM endpoints unavailable")


# ─────────────────────────────────────────────
# MACRO AGENT
# ─────────────────────────────────────────────

class MacroAgent(BaseAgent):
    """
    Analyses macro-economic conditions: VIX, yield curve, sector rotation,
    Fed language, and risk-on/risk-off regime.
    """

    AGENT_NAME = "macro"
    TIMEOUT_SECONDS = 120  # Ollama on CPU needs extra time for macro reasoning

    def run(self) -> AgentSignal:
        self._logger.info(f"MacroAgent running for {self.symbol}")
        system, user_tpl = PromptLoader.get_agent_prompts(self.AGENT_NAME)
        prompt = user_tpl.replace(
            "{symbol}", self.symbol
        ).replace(
            "{today}", datetime.now(timezone.utc).strftime('%Y-%m-%d')
        )
        # Primary: Ollama (local, reliable)
        raw = self._call_ollama(prompt)
        if raw:
            return self._parse_signal_from_json(raw, self.AGENT_NAME)
        # Fallback: Gemini via OpenClaw — bind AgentSignalSchema for structured output
        raw = self._call_openclaw(system, prompt, schema=AgentSignalSchema)
        if raw:
            return self._parse_signal_from_json(raw, self.AGENT_NAME)
        return AgentSignal.neutral(self.AGENT_NAME, "All LLM endpoints unavailable")


# ─────────────────────────────────────────────
# EARNINGS AGENT
# ─────────────────────────────────────────────

class EarningsAgent(BaseAgent):
    """
    Analyses upcoming earnings risk and historical earnings volatility for the symbol.
    Helps the AI Brain reduce position size ahead of earnings events.
    """

    AGENT_NAME = "earnings"
    TIMEOUT_SECONDS = 120  # Ollama on CPU needs extra time

    def run(self) -> AgentSignal:
        self._logger.info(f"EarningsAgent running for {self.symbol}")
        system, user_tpl = PromptLoader.get_agent_prompts(self.AGENT_NAME)
        prompt = user_tpl.replace(
            "{symbol}", self.symbol
        ).replace(
            "{today}", datetime.now(timezone.utc).strftime('%Y-%m-%d')
        )
        # Primary: Ollama (local, reliable)
        raw = self._call_ollama(prompt)
        if raw:
            return self._parse_signal_from_json(raw, self.AGENT_NAME)
        # Fallback: Gemini via OpenClaw — bind AgentSignalSchema for structured output
        raw = self._call_openclaw(system, prompt, schema=AgentSignalSchema)
        if raw:
            return self._parse_signal_from_json(raw, self.AGENT_NAME)
        return AgentSignal.neutral(self.AGENT_NAME, "All LLM endpoints unavailable")


# ─────────────────────────────────────────────
# TECHNICAL AGENT (Ollama — fast, offline)
# ─────────────────────────────────────────────

class TechnicalAgent(BaseAgent):
    """
    Local Ollama-powered cross-timeframe technical analysis.
    Fast and offline — uses Gemma to reason about chart patterns.
    """

    AGENT_NAME = "technical"
    TIMEOUT_SECONDS = 90  # Ollama on CPU needs ~40s

    def run(self) -> AgentSignal:
        self._logger.info(f"TechnicalAgent running for {self.symbol}")
        system, user_tpl = PromptLoader.get_agent_prompts(self.AGENT_NAME)
        
        # Inject Multi-Timeframe Trend context
        trends_str = "No multi-timeframe trend data available."
        if self.market_trends:
            trends_str = json.dumps(self.market_trends, indent=2)
            
        prompt = user_tpl.replace("{symbol}", self.symbol).replace("{market_trends}", trends_str)
        
        # Primary: Ollama (local, fast)
        raw = self._call_ollama(prompt)
        if raw:
            return self._parse_signal_from_json(raw, self.AGENT_NAME)
        
        # Fallback: OpenClaw — bind AgentSignalSchema for structured output
        raw = self._call_openclaw(system, prompt, schema=AgentSignalSchema)
        if raw:
            return self._parse_signal_from_json(raw, self.AGENT_NAME)
        return AgentSignal.neutral(self.AGENT_NAME, "All endpoints unavailable")


# ─────────────────────────────────────────────
# CORRELATION AGENT (Pure-math)
# ─────────────────────────────────────────────

class CorrelationAgent(BaseAgent):
    """
    Detects inter-asset correlation shifts that invalidate mean-reversion.
    Analyses rolling 20-period Pearson correlation across related markets.
    """

    AGENT_NAME = "correlation"

    def run(self) -> AgentSignal:
        """
        Compute correlation health across the inter-market basket for self.symbol.

        Data source priority (Phase 3 §9.1):
          1. Pre-aggregated DataFrames injected by FleetOrchestrator via
             SubAgentPool.market_data_frames → self.dataframes (zero-cost).
          2. Direct MetaTrader5 bar fetch as fallback (requires MT5 module).
          3. Neutral signal if neither is available.

        Returns AgentSignal where:
          - sentiment encodes correlation HEALTH (0.0 = neutral, never directional)
          - Used by `get_vote()` to produce a HOLD or VETO directional decision.
          - Bounded confidence so deliberation can weigh against fresh LLM votes.
        """
        self._logger.info(f"CorrelationAgent running for {self.symbol}")

        from symbol_service import symbol_service
        clean_symbol = symbol_service.get_clean_symbol(self.symbol)
        others = CORRELATION_MAP.get(clean_symbol, [])

        if not others:
            return AgentSignal.neutral(self.AGENT_NAME, f"No correlation mapping for {clean_symbol}")

        import numpy as np
        import pandas as pd

        # ── Source 1: Pre-aggregated DataFrames (preferred, zero-cost) ──
        # `self.dataframes` is injected by SubAgentPool at agent-build time
        # if FleetOrchestrator has computed multi-symbol aggregates.
        injected = getattr(self, "dataframes", None) or {}
        target_close: Optional[pd.Series] = None
        peer_closes: dict[str, pd.Series] = {}

        if isinstance(injected, dict) and injected:
            # Look for a 1h-aligned frame for the target
            target_frame = injected.get("1h") or injected.get("15m") or injected.get("1m")
            if isinstance(target_frame, pd.DataFrame) and "close" in target_frame.columns:
                target_close = target_frame["close"].astype(float)

        # ── Source 2: Direct MT5 fetch (fallback) ──
        if target_close is None or len(target_close) < 20:
            if _mt5 is None:
                return AgentSignal.neutral(
                    self.AGENT_NAME,
                    "No DataFrame injection and MetaTrader5 module unavailable",
                )
            broker_target = symbol_service.get_broker_symbol(clean_symbol)
            rates = _mt5.copy_rates_from_pos(broker_target, _mt5.TIMEFRAME_H1, 0, 50)
            if rates is None or len(rates) < 20:
                return AgentSignal.neutral(
                    self.AGENT_NAME, "Insufficient price history for target"
                )
            df_target = pd.DataFrame(rates)
            target_close = df_target["close"].astype(float)

        correlations: list[float] = []
        objections: list[str] = []

        # Fetch closes for each correlated symbol — fall back to MT5 per peer
        for other in others:
            other_close: Optional[pd.Series] = None
            broker_other = symbol_service.get_broker_symbol(other)
            if _mt5 is not None:
                o_rates = _mt5.copy_rates_from_pos(broker_other, _mt5.TIMEFRAME_H1, 0, 50)
                if o_rates is not None and len(o_rates) >= 20:
                    df_other = pd.DataFrame(o_rates)
                    other_close = df_other["close"].astype(float)
            if other_close is None or len(other_close) < 20:
                continue
            peer_closes[other] = other_close

            min_len = min(len(target_close), len(other_close))
            corr = target_close.tail(min_len).corr(other_close.tail(min_len))

            if not np.isnan(corr):
                correlations.append(corr)
                # Flag if correlation is unusually weak or inverted for highly correlated pairs
                if other in ("GBPUSD", "ETHUSD", "US100", "US500") and corr < 0.6:
                    objections.append(
                        f"Correlation break: {clean_symbol} ↔ {other} is weak ({corr:.2f})"
                    )
                elif other == "DXY" and corr > -0.6:
                    # DXY usually inversely correlated with majors/gold
                    objections.append(
                        f"Correlation break: {clean_symbol} ↔ DXY not inverse enough ({corr:.2f})"
                    )

        if not correlations:
            return AgentSignal.neutral(self.AGENT_NAME, "Failed to compute any correlations")

        avg_abs_corr = float(np.mean([abs(c) for c in correlations]))

        # Health: 1.0 = all pairs aligned; each broken correlation deducts 0.4
        health = 1.0 - (len(objections) * 0.4)
        health = max(-1.0, min(1.0, health))

        reasoning = f"Avg |correlation|={avg_abs_corr:.2f} across {len(correlations)} peers. "
        if objections:
            reasoning += "Alerts: " + " | ".join(objections)
        else:
            reasoning += "Inter-market correlations are healthy and aligned."

        return AgentSignal(
            agent=self.AGENT_NAME,
            sentiment=health,
            confidence=0.8,
            reasoning=reasoning,
            sources=["DataFrame injection" if injected else "MT5 Live Ticks", "Inter-market Mapper"],
        )

    def get_vote(self) -> AgentVote:
        """
        Gate vote based on correlation health (Phase 3 §3.1).

        Decision matrix:
          - health < -0.4  → VETO  (≥2 correlation breaks — regime invalidated)
          - health < 0     → HOLD  (1 break — soft warning, reduced confidence)
          - health ≥ 0     → HOLD  (healthy — defer to panel direction)

        Weight 1.25 is set on the AgentVote directly (gates do not use the
        panel `_static` weights table).
        """
        try:
            signal = self.run()
        except Exception as e:
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="HOLD",
                confidence=0.0,
                reasoning=f"CorrelationAgent.run() failed: {e}",
                weight=1.25,
            )

        if signal.confidence < 0.1:
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="HOLD",
                confidence=0.1,
                reasoning=signal.reasoning[:200],
                weight=1.25,
            )

        if signal.sentiment < -0.4:
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="VETO",
                confidence=signal.confidence,
                reasoning=f"CORRELATION BREAK: {signal.reasoning[:200]}",
                veto_reason=signal.reasoning[:120],
                weight=1.25,
            )

        if signal.sentiment < 0:
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="HOLD",
                confidence=0.4,
                reasoning=f"Correlation weakening: {signal.reasoning[:150]}",
                weight=1.25,
            )

        return AgentVote(
            agent=self.AGENT_NAME,
            vote="HOLD",
            confidence=0.7,
            reasoning=f"Correlations healthy. {signal.reasoning[:150]}",
            weight=1.25,
        )


# ─────────────────────────────────────────────
# WATCHMAN AGENT (Market Quality)
# ─────────────────────────────────────────────

class WatchmanAgent(BaseAgent):
    """
    The Market Watchman monitors order-flow quality using MT5 Level 1 data.
    It does NOT use an LLM — it's a pure-math statistical agent.

    Metrics:
      · bid_ask_spread_pct — if > 0.15%, market quality degrades
      · volume_spike_ratio — current vs. 20-period avg; ratio > 3× flags institutions

    Returns an AgentVote (not AgentSignal) with market_quality score 0.0 – 1.0.
    Also returns a standard AgentSignal for backward compat with the AI Brain.
    """

    AGENT_NAME = "watchman"

    # Thresholds
    BAD_SPREAD_PCT: float = 0.15    # > this %, market quality degrades
    INSTITUTION_SPIKE: float = 3.0  # volume > this × average → flag
    MIN_QUALITY_VETO: float = 0.25  # below this, Watchman issues VETO

    def run(self) -> AgentSignal:
        """Run market quality check and return as AgentSignal (for AI Brain compat)."""
        vote = self.get_vote()
        # Map quality score to sentiment scale for AI Brain
        sentiment = (vote.confidence - 0.5) * 2  # 0.5 qual → 0.0, 1.0 → +1.0
        return AgentSignal(
            agent=self.AGENT_NAME,
            sentiment=sentiment,
            confidence=vote.confidence,
            reasoning=vote.reasoning,
        )

    def get_vote(
        self,
        mt5_client=None,     # Optional live MT5 client for real data
        price_history=None,     # Optional deque of {price, volume} dicts
    ) -> AgentVote:
        """
        Compute market quality score from available data.
        Falls back to HOLD with high confidence if no live data is available,
        ensuring the Watchman never blocks trades due to missing data.
        """
        try:
            quality, alert = self._assess_quality(mt5_client, price_history)
        except Exception as e:
            self._logger.warning(f"WatchmanAgent quality check failed: {e}")
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="HOLD",
                confidence=0.7,
                reasoning="Market quality check unavailable — defaulting to HOLD (permissive).",
                weight=1.25,
            )

        if quality < self.MIN_QUALITY_VETO:
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="VETO",
                confidence=quality,
                reasoning=f"Market quality too poor to trade ({quality:.2f} < {self.MIN_QUALITY_VETO}): {alert}",
                weight=1.25,
                veto_reason=alert or "Low market quality",
            )

        # Map quality score to directional vote
        # Watchman doesn't pick direction — it either permits or vetoes
        return AgentVote(
            agent=self.AGENT_NAME,
            vote="HOLD",   # Watchman is neutral on direction; it only gates quality
            confidence=quality,
            reasoning=f"Market quality OK ({quality:.2f}). {alert or 'No anomalies detected.'}",
            weight=1.25,
        )

    def _assess_quality(self, mt5_client, price_history) -> tuple[float, Optional[str]]:
        """Compute market quality score (0.0–1.0) from available inputs."""
        import numpy as np

        quality = 1.0
        alerts = []

        # Use local price history if available
        if price_history and len(price_history) >= 5:
            prices = [p["price"] for p in price_history if "price" in p]
            volumes = [p.get("volume", 0) for p in price_history]

            if len(prices) >= 5:
                # Estimate spread from price volatility (proxy when no bid/ask)
                returns = np.diff(prices[-20:]) if len(prices) >= 20 else np.diff(prices)
                volatility = float(np.std(returns)) if len(returns) > 0 else 0.0
                last_price = prices[-1] if prices[-1] > 0 else 1.0
                spread_proxy_pct = (volatility / last_price) * 100

                if spread_proxy_pct > self.BAD_SPREAD_PCT:
                    penalty = min(0.4, spread_proxy_pct / self.BAD_SPREAD_PCT * 0.2)
                    quality -= penalty
                    alerts.append(f"High spread proxy ({spread_proxy_pct:.3f}%)")

            if volumes and any(v > 0 for v in volumes):
                valid_vols = [v for v in volumes if v > 0]
                avg_vol = np.mean(valid_vols[:-1]) if len(valid_vols) > 1 else valid_vols[0]
                cur_vol = valid_vols[-1]
                if avg_vol > 0:
                    spike_ratio = cur_vol / avg_vol
                    if spike_ratio > self.INSTITUTION_SPIKE:
                        penalty = min(0.3, (spike_ratio / self.INSTITUTION_SPIKE) * 0.1)
                        quality -= penalty
                        alerts.append(f"Volume spike {spike_ratio:.1f}× avg (institution block?)")

        quality = max(0.0, min(1.0, quality))
        alert_str = " | ".join(alerts) if alerts else None
        return quality, alert_str


# ─────────────────────────────────────────────
# ORDER FLOW AGENT (Phase 4 §3.2)
# ─────────────────────────────────────────────

class OrderFlowAgent(BaseAgent):
    """
    Order Flow & Volume Profile Agent — Pure-math gate, no LLM.

    Analyses tick-level volume distribution to detect institutional
    accumulation (buying into dips) vs. distribution (selling into rallies).

    Metrics:
      · Cumulative delta: Σ(buy_volume — sell_volume) over the last 500 ticks
      · Delta divergence: price making new highs while delta is declining → distribution
      · Volume-weighted average price (VWAP) displacement vs. current price
        Above VWAP → premium (sellers active); below VWAP → discount (buyers active).

    Decision matrix (gate, weight=1.5 baked into the AgentVote):
      · Extreme distribution (delta < -0.7 z-score AND price above VWAP):
        VETO on BUY signals — institutions are selling, not buying.
      · Accumulation (delta > +0.5 z-score, price below VWAP):
        HOLD with strong confidence (favours buying on dips).
      · Neutral: HOLD (no institutional footprint detected).
    """

    AGENT_NAME = "orderflow"
    TICK_WINDOW = 500          # last N ticks to analyse
    DELTA_Z_VETO = -0.7        # cumulative delta below this z-score → VETO
    DELTA_Z_ACCUMULATION = 0.5  # above this → accumulation detected

    def run(self) -> AgentSignal:
        return AgentSignal.neutral(self.AGENT_NAME, "OrderFlow agent is pure-math, not LLM-based.")

    def get_vote(
        self,
        raw_signal: str = "",
        price_history=None,
    ) -> AgentVote:
        """
        Analyse tick-level order flow and return a gate vote.

        Data sources (best-effort):
          1. MT5 tick buffer via `mt5_hub.get_tick(symbol)` → last tick bid/ask/volume
          2. `price_history` deque of {price, volume} dicts (BotEngine provides this)
          3. Falls back to HOLD with neutral confidence when no data is available.
        """
        import numpy as np

        # ── Source 1: MT5 tick buffer ──────────────────────────────────
        tick_bid, tick_ask, tick_vol = None, None, 0.0
        try:
            mt5_tick = mt5_hub.get_tick(self.symbol)
            if mt5_tick:
                tick_bid = getattr(mt5_tick, "bid", None) or getattr(mt5_tick, "_bid", None)
                tick_ask = getattr(mt5_tick, "ask", None) or getattr(mt5_tick, "_ask", None)
                tick_vol = getattr(mt5_tick, "volume", 0.0) or getattr(mt5_tick, "_volume", 0.0)
        except Exception:
            pass

        # ── Source 2: price_history → pseudo-tick volume + price ───────
        # We only have per-trade volume from the tick pipeline, not buy/sell
        # breakdown. We proxy delta by comparing consecutive price directions:
        #   price↑ on volume → volume counted as buy
        #   price↓ on volume → volume counted as sell
        if not price_history or len(price_history) < 10:
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="HOLD",
                confidence=0.3,
                reasoning="Insufficient tick-level price history for order flow analysis.",
                weight=1.5,
            )

        prices = [float(p.get("price", 0)) for p in price_history]
        volumes = [float(p.get("volume", 0)) for p in price_history]
        window_size = min(self.TICK_WINDOW, len(prices))

        # Build pseudo buy/sell delta from directional tick volume
        buy_vol = 0.0
        sell_vol = 0.0
        for i in range(max(1, len(prices) - window_size), len(prices)):
            dp = prices[i] - prices[i - 1]
            vol = volumes[i] if i < len(volumes) else 0.0
            if dp > 0:
                buy_vol += vol
            elif dp < 0:
                sell_vol += vol

        delta = buy_vol - sell_vol
        total_vol = buy_vol + sell_vol

        # ── Delta z-score (normalised by total volume) ─────────────────
        # When buy_vol == sell_vol the delta is zero. A strong negative
        # delta in absolute terms is the distribution signal.
        if total_vol < 1e-6:
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="HOLD",
                confidence=0.3,
                reasoning="Zero total volume — cannot assess order flow balance.",
                weight=1.5,
            )

        # Mean delta over the window (expectation ≈ 0 when balanced)
        # We normalise by sqrt(total_vol) as a simple statistical proxy
        delta_z = float(delta / np.sqrt(max(1.0, total_vol)))

        # ── VWAP displacement ──────────────────────────────────────────
        win_prices = prices[-window_size:]
        win_vols = volumes[-window_size:]
        vwap_num = sum(p * v for p, v in zip(win_prices, win_vols) if v > 0)
        vwap_den = sum(v for v in win_vols if v > 0)
        vwap = vwap_num / max(vwap_den, 1e-6)

        current_price = win_prices[-1] if win_prices else 0.0
        displacement_pct = ((current_price - vwap) / vwap * 100) if vwap > 0 else 0.0

        # ── Decision logic ─────────────────────────────────────────────
        reasoning_parts = [
            f"delta_z={delta_z:.2f} (total_vol={total_vol:.0f})",
            f"vwap_displacement={displacement_pct:+.2f}%",
        ]

        # Extreme distribution: VETO on BUY signals
        if delta_z < self.DELTA_Z_VETO and raw_signal == "BUY" and displacement_pct > 0:
            reasoning = (
                f"ORDERFLOW VETO: Extreme distribution detected (delta_z={delta_z:.2f}). "
                f"Price above VWAP ({displacement_pct:+.2f}%) — institutions selling into "
                f"rallies. Blocking BUY entry. {' | '.join(reasoning_parts)}"
            )
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="VETO",
                confidence=min(0.9, abs(delta_z) * 0.6),
                reasoning=reasoning[:300],
                veto_reason=f"Order flow distribution (delta_z={delta_z:.2f}, VWAP={displacement_pct:+.1f}%)",
                weight=1.5,
            )

        # Accumulation: delta strongly positive + price discount
        if delta_z > self.DELTA_Z_ACCUMULATION and displacement_pct < 0:
            reasoning = (
                f"Order flow shows accumulation (delta_z={delta_z:.2f}, "
                f"VWAP gap={displacement_pct:+.2f}%). Institutional buying "
                f"at discount — favourable for long entries. "
                f"{' | '.join(reasoning_parts)}"
            )
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="HOLD",
                confidence=0.75,
                reasoning=reasoning[:300],
                weight=1.5,
            )

        # Net selling in the book
        if delta_z < -0.3:
            reasoning = (
                f"Order flow shows mild distribution (delta_z={delta_z:.2f}). "
                f"{' | '.join(reasoning_parts)}"
            )
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="HOLD",
                confidence=0.4,
                reasoning=reasoning[:250],
                weight=1.5,
            )

        # Net buying or flat
        reasoning = (
            f"Order flow balanced/accumulative (delta_z={delta_z:.2f}). "
            f"{' | '.join(reasoning_parts)}"
        )
        return AgentVote(
            agent=self.AGENT_NAME,
            vote="HOLD",
            confidence=0.7,
            reasoning=reasoning[:250],
            weight=1.5,
        )


# ─────────────────────────────────────────────
# CALENDAR AGENT (Phase 4 §3.4)
# ─────────────────────────────────────────────

# Recurring high-impact economic events with their typical cadence.
# Each entry: (month_day, event_name, impact_minutes_before, impact_minutes_after)
# impact_minutes_before = window during which entries are VETO'd (usually 30 min)
# impact_minutes_after  = window after the event during which confidence is reduced
#
# This is a best-effort calendar. A full implementation would pull from an
# economic calendar API (ForexFactory, Investing.com). The hardcoded list
# covers the highest-volume events that reliably move forex markets.
_ECONOMIC_CALENDAR: list[tuple[int, str, int, int]] = [
    # US Federal Reserve
    (0,    "FOMC Rate Decision + Press Conference", 30, 120),  # day 0 = check any Wed
    (0,    "FOMC Minutes",                           30,  90),
    # US Labour market
    (0,    "Non-Farm Payrolls (NFP)",                30, 120),  # first Friday
    (0,    "CPI (Consumer Price Index)",             30, 120),
    (0,    "PPI (Producer Price Index)",             30,  90),
    (0,    "Retail Sales (US)",                      30,  90),
    (0,    "GDP (Advance)",                          30, 120),
    # Central Banks
    (0,    "ECB Rate Decision",                      30, 120),
    (0,    "BOE Rate Decision",                      30, 120),
    (0,    "BOJ Rate Decision",                      30, 120),
    # PMIs
    (0,    "ISM Manufacturing PMI",                  30,  90),
    (0,    "ISM Services PMI",                       30,  90),
    # Monthly
    (0,    "Fed Beige Book",                         30,  60),
]

# Important days of the month that always carry calendar risk
_IMPORTANT_CALENDAR_DAYS = frozenset({
    1,    # ISM Manufacturing PMI
    3,    # ADP / Services PMI
    7,    # NFP / Employment
    12,   # CPI
    15,   # Retail Sales / PPI
    22,   # Existing Home Sales
    28,   # GDP (Advance)
})


def _is_high_impact_window(now_utc: "datetime") -> tuple[bool, Optional[str], Optional[int]]:
    """
    Quick heuristic: returns (is_veto, event_name, minutes_remaining_in_veto).

    Strategy:
      · Weekdays only (excludes Saturday/Sunday).
      · If the calendar day-of-month is in the known high-impact list AND
        we're within the NY/London session window (0800–1600 UTC), flag it.
      · Historical data shows the vast majority of high-impact events cluster
        around 0830, 1000, 1230, 1400, 1600 UTC. We apply a blanket 30 min
        VETO window around ALL those times on high-impact calendar days.
    """
    wd = now_utc.weekday()  # 0=Mon, 6=Sun
    if wd >= 5:
        return False, None, None

    day = now_utc.day
    hour = now_utc.hour
    minute = now_utc.minute

    # Known event release times (UTC): NFP 1330, CPI 1330, FOMC 1900, ISM 1500, etc.
    # We widen to a blanket rule: high-impact calendar days in session hours.
    if day in _IMPORTANT_CALENDAR_DAYS and 8 <= hour <= 18:
        # Check against the most common release times
        _release_times = [
            (8, 30), (9, 30), (10, 0), (12, 30),
            (13, 30), (14, 0), (15, 0), (16, 0), (18, 0),
        ]
        now_mins = hour * 60 + minute
        for rh, rm in _release_times:
            r_mins = rh * 60 + rm
            delta = now_mins - r_mins
            if 0 <= delta <= 30:
                event_name = f"High-impact calendar cluster (day {day}, {rh:02d}:{rm:02d} UTC)"
                return True, event_name, 30 - delta
            if -30 <= delta < 0:
                event_name = f"High-impact calendar cluster (day {day}, {rh:02d}:{rm:02d} UTC)"
                return True, event_name, abs(delta)

    return False, None, None


class CalendarAgent(BaseAgent):
    """
    Economic Calendar Gate (Phase 4 §3.4).

    Purely event-time-based — no LLM, no API call. The agent checks whether
    the current UTC timestamp falls within a VETO window of a known
    high-impact economic event.

    Decision:
      · ±30 min of a known release → VETO (no entries)
      · ±2h of a known release → HOLD with reduced confidence (0.4)
      · Otherwise → HOLD with 0.7 confidence (no calendar risk)

    Weight: N/A (veto-only gate — weight is on the VETO itself).
    This agent also participates in the gate section of `deliberate()`.
    """

    AGENT_NAME = "calendar"
    VETO_WINDOW_MINUTES = 30
    WARNING_WINDOW_MINUTES = 120

    def run(self) -> AgentSignal:
        return AgentSignal.neutral(self.AGENT_NAME, "Calendar agent is event-time-based, not LLM.")

    def get_vote(self) -> AgentVote:
        from datetime import timezone as _tz
        now_utc = datetime.now(_tz.utc)

        is_veto, event_name, mins_remain = _is_high_impact_window(now_utc)

        if is_veto:
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="VETO",
                confidence=1.0,
                reasoning=f"CALENDAR VETO: Within ±{self.VETO_WINDOW_MINUTES}min of {event_name}. "
                          f"No new entries permitted until the event passes.",
                veto_reason=event_name or "Economic calendar event window",
                weight=1.0,
            )

        # Check warning window (within ±2h of any event on a high-impact day)
        if now_utc.day in _IMPORTANT_CALENDAR_DAYS and now_utc.weekday() < 5:
            hour = now_utc.hour
            # Broad session check: if within ~2h of common release times
            _release_hours = {8, 9, 10, 12, 13, 14, 15, 16, 18}
            near_event = any(abs(hour - rh) <= 2 for rh in _release_hours)
            if near_event and 6 <= hour <= 20:
                return AgentVote(
                    agent=self.AGENT_NAME,
                    vote="HOLD",
                    confidence=0.4,
                    reasoning=f"Calendar awareness: possible economic event within "
                              f"±{self.WARNING_WINDOW_MINUTES}min (day {now_utc.day}). "
                              f"Confidence reduced — defer to LLM panel.",
                    weight=1.0,
                )

        return AgentVote(
            agent=self.AGENT_NAME,
            vote="HOLD",
            confidence=0.7,
            reasoning="No economic calendar events within VETO or warning window.",
            weight=1.0,
        )


# ─────────────────────────────────────────────
# ICT SMART MONEY AGENT (Pure-math, no LLM)
# ─────────────────────────────────────────────

class ICTAgent(BaseAgent):
    """
    ICT Smart Money Structure Agent — Pure-math, no LLM.

    Identifies institutional "footprints" in price action:
      · Liquidity Sweeps (stop hunts below swing lows)
      · Fair Value Gaps (displacement candles)
      · Kill Zone timing (NY + London open windows)
      · Market Structure Shifts (break of structure)

    Returns an AgentVote based on the Smart Money narrative:
      - If sweep + FVG + kill zone align → strong BUY vote
      - If no institutional footprints → HOLD (neutral)
    """

    AGENT_NAME = "ict"

    def run(self) -> AgentSignal:
        """For AI Brain compat — returns neutral signal (ICT agent is tick-driven)."""
        return AgentSignal.neutral(self.AGENT_NAME, "ICT agent is tick-driven, not forecast-based.")

    def get_vote(
        self,
        price_history=None,
        confluence_ict = None,
    ) -> AgentVote:
        """
        Analyse recent OHLC data for ICT structural patterns.

        Called during deliberation with the bot's live price history and
        optionally the ICT diagnostics already computed by the confluence gate.

        If confluence_ict is provided (from ConfluenceResult.to_dict()),
        we reuse the pre-computed FVG/sweep/conviction data to avoid
        redundant computation.

        Parameters:
            price_history   : list of dicts with {price, high, low, close, volume, time}
            confluence_ict  : Pre-computed ICT diagnostics from ConfluenceResult
        """
        import pandas as pd
        from datetime import datetime, timezone, time as dt_time

        # ── Fast path: reuse pre-computed ICT diagnostics ────────────
        if confluence_ict is not None:
            fvg = confluence_ict.get("fvg_detected")
            sweep = confluence_ict.get("liquidity_sweep")
            kill_zone = confluence_ict.get("kill_zone_active", True)
            conviction = confluence_ict.get("ict_conviction", "STANDARD")

            return self._build_vote(fvg, sweep, kill_zone, conviction)

        # ── Slow path: compute from raw price history ────────────────
        if not price_history or len(price_history) < 25:
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="HOLD",
                confidence=0.2,
                reasoning="Insufficient price history for ICT analysis.",
                weight=1.0,
            )

        try:
            from confluence import detect_fvg, detect_liquidity_sweep

            highs = pd.Series([p.get("high", p["price"]) for p in price_history])
            lows = pd.Series([p.get("low", p["price"]) for p in price_history])
            closes = pd.Series([p.get("close", p["price"]) for p in price_history])

            fvg = detect_fvg(highs, lows, closes)
            sweep = detect_liquidity_sweep(highs, lows, closes)

            # Check Kill Zone timing
            now_utc = datetime.now(timezone.utc).time()
            kill_zone = self._check_kill_zone(now_utc)

            # Compute conviction
            ict_count = sum([
                fvg is not None,
                sweep is not None,
                kill_zone,
            ])
            if ict_count >= 3:
                conviction = "MAXIMUM"
            elif ict_count >= 2:
                conviction = "HIGH"
            else:
                conviction = "STANDARD"

            return self._build_vote(fvg, sweep, kill_zone, conviction)

        except Exception as e:
            self._logger.warning(f"ICTAgent analysis error: {e}")
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="HOLD",
                confidence=0.2,
                reasoning=f"ICT analysis error: {str(e)[:100]}",
                weight=1.0,
            )

    def _build_vote(self, fvg, sweep, kill_zone, conviction) -> AgentVote:
        """Convert ICT diagnostics into a directional AgentVote."""
        parts = []

        if sweep:
            parts.append(
                f"Sell-side liquidity sweep detected "
                f"(swing_low={sweep.get('swing_low')}, "
                f"depth={sweep.get('sweep_depth_pct', 0):.2f}%)"
            )
        if fvg:
            parts.append(
                f"Bullish FVG detected "
                f"(gap={fvg.get('gap_size_pct', 0):.2f}%, "
                f"{fvg.get('bars_ago', '?')} bars ago)"
            )
        if kill_zone:
            parts.append("Inside Kill Zone (institutional session)")

        if conviction == "MAXIMUM":
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="BUY",
                confidence=0.85,
                reasoning=f"ICT MAXIMUM conviction: {' | '.join(parts)}",
                weight=1.0,
            )
        elif conviction == "HIGH":
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="BUY",
                confidence=0.5,
                reasoning=f"ICT HIGH conviction: {' | '.join(parts)}",
                weight=1.0,
            )
        else:
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="HOLD",
                confidence=0.3,
                reasoning="No institutional footprints detected. Smart Money is quiet.",
                weight=1.0,
            )

    @staticmethod
    def _check_kill_zone(now_utc) -> bool:
        """Check if the current UTC time falls within a Kill Zone window."""
        from datetime import time as dt_time
        ny_start = dt_time(13, 30)
        ny_end = dt_time(16, 0)
        london_start = dt_time(7, 0)
        london_end = dt_time(10, 0)

        return (ny_start <= now_utc <= ny_end) or (london_start <= now_utc <= london_end)


# ─────────────────────────────────────────────
# RISK MANAGER AGENT (Kelly gating)
# ─────────────────────────────────────────────

class RiskManagerAgent(BaseAgent):
    """
    Kelly Criterion gating agent.  Wraps position_sizer.py logic and acts as
    the last checkpoint before ExecutionerAgent fires an order.

    This is a pure-math agent — no LLM call. It either approves the trade
    at a Kelly-optimal qty, or issues a VETO with a clear reason.

    Veto conditions:
      · Kelly fraction ≤ 0  (negative expectancy)
      · Account in ORGAN_FAILURE survival state
      · Daily drawdown limit already breached
    """

    AGENT_NAME = "risk_manager"

    def run(self) -> AgentSignal:
        """For AI Brain compat — returns neutral signal (Risk Manager doesn't forecast)."""
        return AgentSignal.neutral(self.AGENT_NAME, "Risk Manager is a gating agent, not a forecaster.")

    def get_vote(
        self,
        signal: str,            # "BUY" | "SELL"
        requested_qty: float,
        equity: float,
        daily_pnl: float,
        starting_equity: float,
        max_daily_drawdown_pct: float,
        recent_trades: list,    # list of trade dicts with {"pnl"} fields
        survival_state: str,    # from BotVitalSigns
    ) -> tuple["AgentVote", int]:
        """
        Evaluate trade risk and return (AgentVote, approved_qty).

        Returns:
            (vote, approved_qty) where vote.vote is "BUY"/"SELL" if approved
            or "VETO" if blocked. approved_qty is 0 on VETO.
        """
        try:
            from position_sizer import PositionSizer, SurvivalState
        except ImportError:
            # If position_sizer is unavailable, default to permit with requested qty
            return AgentVote(
                agent=self.AGENT_NAME,
                vote=signal,
                confidence=0.5,
                reasoning="PositionSizer unavailable — using requested qty.",
                weight=1.0,
            ), requested_qty

        # ── Survival state gate ────────────────────────────────────────────
        if survival_state in ("ORGAN_FAILURE", "FLATLINE"):
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="VETO",
                confidence=1.0,
                reasoning=f"Account in {survival_state} — all new positions blocked.",
                weight=1.0,
                veto_reason=f"Survival state: {survival_state}",
            ), 0

        # ── Daily drawdown gate ────────────────────────────────────────────
        if starting_equity > 0:
            daily_dd_pct = ((starting_equity - equity) / starting_equity) * 100
            if daily_dd_pct >= max_daily_drawdown_pct:
                return AgentVote(
                    agent=self.AGENT_NAME,
                    vote="VETO",
                    confidence=1.0,
                    reasoning=(
                        f"Daily drawdown {daily_dd_pct:.2f}% ≥ limit {max_daily_drawdown_pct:.2f}%. "
                        f"No new positions today."
                    ),
                    weight=1.0,
                    veto_reason=f"Daily drawdown limit breached ({daily_dd_pct:.2f}%)",
                ), 0

        # ── Kelly Criterion sizing ─────────────────────────────────────────
        try:
            sizer = PositionSizer(
                survival_state=SurvivalState(survival_state)
                if survival_state in [s.value for s in SurvivalState]
                else None
            )
            kelly_qty = sizer.compute(
                equity=equity,
                recent_trades=recent_trades,
                current_price=1.0,   # qty already computed upstream
            )
            # Cap kelly_qty at the requested qty
            approved_qty = min(float(kelly_qty), requested_qty)
        except Exception as e:
            self._logger.warning(f"Kelly computation error: {e} — using requested qty")
            approved_qty = requested_qty

        if approved_qty <= 0:
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="VETO",
                confidence=0.9,
                reasoning="Kelly Criterion returned 0 — negative or zero expectancy edge.",
                weight=1.0,
                veto_reason="Kelly fraction ≤ 0 (no edge)",
            ), 0

        return AgentVote(
            agent=self.AGENT_NAME,
            vote=signal,
            confidence=min(1.0, approved_qty / max(requested_qty, 1)),
            reasoning=f"Kelly approved {approved_qty}/{requested_qty} shares. Survival: {survival_state}.",
            weight=1.0,
        ), approved_qty


class CROAgent(BaseAgent):
    """
    Chief Risk Officer — Adversarial Agent.

    Receives the proposed trade and actively generates reasons NOT to take it.
    Issues VETO if >= 2 structural objections are found.

    This agent does NOT forecast direction. It only blocks bad entries.
    Prompt persona: a skeptical, risk-first analyst who has been burned before
    and whose job security depends on stopping bad trades, not enabling them.

    Veto conditions it checks:
      · Upcoming earnings within 48h (catalyst risk)
      · Macro regime RISK_OFF (VIX > 25, or macro agent sentiment < -0.5)
      · Position correlated with another open position in the fleet
      · Conviction not justified by recent agent disagreement
      · Price extended far from VWAP (overextension risk)
    """

    AGENT_NAME = "cro"
    TIMEOUT_SECONDS = 90

    def run(self) -> AgentSignal:
        # CRO does not produce a general market signal — return neutral for AI Brain compat
        return AgentSignal.neutral(self.AGENT_NAME, "CRO is an adversarial gating agent.")

    def get_vote(
        self,
        raw_signal: str,
        symbol: str,
        panel_votes: list["AgentVote"],
        macro_signal: Optional["AgentSignal"] = None,
        price_history=None,
    ) -> "AgentVote":
        """
        Evaluate structural risks and return a vote or VETO.

        Parameters:
            raw_signal:   "BUY" or "SELL" from the Strategist
            symbol:       trading symbol
            panel_votes:  already-cast votes from the panel
            macro_signal: the MacroAgent's latest AgentSignal (if available)
            price_history: deque of price bars for VWAP/extension checks
        """
        objections: list[str] = []

        # ── Objection 1: Macro regime RISK_OFF ─────────────────────────
        if macro_signal and macro_signal.sentiment < -0.5 and macro_signal.confidence > 0.5:
            objections.append(
                f"Macro regime RISK_OFF (sentiment={macro_signal.sentiment:.2f}). "
                f"Reason: {macro_signal.reasoning[:100]}"
            )

        # ── Objection 2: Panel strongly disagrees ───────────────────────
        oppose_count = sum(
            1 for v in panel_votes
            if v.vote not in (raw_signal, "HOLD", "VETO")
            and v.confidence > 0.6
        )
        if oppose_count >= 2:
            objections.append(
                f"{oppose_count} high-confidence panel agents oppose this {raw_signal}. "
                f"Significant disagreement without consensus is a structural red flag."
            )

        # ── Objection 3: Upcoming Earnings Risk ────────────────────────
        earnings_vote = next((v for v in panel_votes if v.agent == "earnings"), None)
        if earnings_vote and earnings_vote.vote == "VETO":
            objections.append(
                f"High catalyst risk: EarningsAgent issued a VETO. "
                f"Reasoning: {earnings_vote.reasoning[:100]}"
            )

        # ── Objection 4: VWAP Overextension ────────────────────────────
        if price_history and len(price_history) >= 20:
            try:
                # Calculate simple VWAP: sum(price * volume) / sum(volume)
                total_pv = sum(float(b.get("c", 0) or b.get("price", 0)) * float(b.get("v", 1) or b.get("volume", 1)) for b in price_history)
                total_v = sum(float(b.get("v", 1) or b.get("volume", 1)) for b in price_history)
                if total_v > 0:
                    vwap = total_pv / total_v
                    current_price = float(price_history[-1].get("c", 0) or price_history[-1].get("price", 0))
                    dist_pct = (current_price - vwap) / vwap * 100
                    
                    # VETO if buying way above VWAP or selling way below VWAP
                    if raw_signal == "BUY" and dist_pct > 2.5:
                        objections.append(f"Price is overextended ({dist_pct:.2f}% above VWAP). Buying here risks catching a blow-off top.")
                    elif raw_signal == "SELL" and dist_pct < -2.5:
                        objections.append(f"Price is overextended ({dist_pct:.2f}% below VWAP). Selling here risks shorting into a parabolic bottom.")
            except Exception as e:
                self._logger.debug(f"CRO VWAP check error: {e}")

        # ── Objection 5: Fleet Correlation + Hard Capacity Gate ────────
        try:
            from fleet import fleet
            active_bots = [
                b for b in fleet._bots.values()
                if b.engine and getattr(b.engine, "position_qty", 0) > 0
            ]
            active_count = len(active_bots)
            active_symbols = [b.config.symbol for b in active_bots]
            max_open = getattr(fleet._fleet_config, "max_open_positions", 6)

            if symbol in active_symbols:
                objections.append(
                    f"Position already open for {symbol} in the fleet. "
                    f"Cross-bot symbol duplication increases idiosyncratic risk."
                )

            if active_count >= max_open:
                # Hard capacity VETO — bypass objection count, return immediately
                return AgentVote(
                    agent=self.AGENT_NAME,
                    vote="VETO",
                    confidence=1.0,
                    reasoning=(
                        f"CRO HARD VETO: Fleet at max open position cap "
                        f"({active_count}/{max_open}). No new entries until existing positions close."
                    ),
                    weight=1.5,
                    darwinian_weight=1.0,
                    veto_reason=f"Fleet max_open_positions cap reached ({active_count}/{max_open})",
                )
        except Exception as e:
            self._logger.debug(f"CRO Fleet check error: {e}")

        # ── Objection 6: LLM-generated structural check ─────────────────
        # Ask the LLM to find one more structural reason not to trade.
        panel_summary = "; ".join(
            f"{v.agent}={v.vote}({v.confidence:.1f})" for v in panel_votes
        )
        
        system, user_tpl = PromptLoader.get_agent_prompts(self.AGENT_NAME)
        prompt = user_tpl.replace(
            "{raw_signal}", raw_signal
        ).replace(
            "{symbol}", symbol
        ).replace(
            "{panel_summary}", panel_summary
        ).replace(
            "{now_utc}", datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        )

        raw = self._call_ollama(prompt)
        if not raw:
            # Bind CROObjectionSchema for structured output
            raw = self._call_openclaw(system, prompt, include_search=False, schema=CROObjectionSchema)

        if raw:
            try:
                parsed_dict = self._extract_json(raw)
                validated = CROObjectionSchema(**parsed_dict)
                
                obj = validated.objection.strip()
                severity = validated.severity
                confidence = validated.confidence
                
                if obj and severity > 0.5 and confidence > 0.5:
                    objections.append(f"[LLM CRO] {obj}")
            except Exception as e:
                self._logger.debug(f"CRO LLM parse/validation error: {e}")

        # ── Verdict ─────────────────────────────────────────────────────
        if len(objections) >= 2:
            reason = " | ".join(objections)
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="VETO",
                confidence=0.9,
                reasoning=f"CRO VETO: {len(objections)} structural objections: {reason[:300]}",
                weight=1.5,
                darwinian_weight=1.0,
                veto_reason=reason[:200],
            )

        # One objection or none — do not veto, but flag in reasoning
        flag = f" [CRO flagged: {objections[0][:100]}]" if objections else ""
        return AgentVote(
            agent=self.AGENT_NAME,
            vote=raw_signal,   # No objection strong enough — defer to panel
            confidence=0.7,
            reasoning=f"CRO review complete. No structural veto.{flag}",
            weight=1.5,
            darwinian_weight=1.0,
        )


# ─────────────────────────────────────────────
# CROSS-TIMEFRAME TREND AGENT (Pure-math, no LLM)
# ─────────────────────────────────────────────

class CrossTimeframeTrendAgent(BaseAgent):
    """
    Formalises the multi-timeframe trend data into a voting agent.
    Checks alignment across 1m, 15m, 1h, 1d timeframes.
    Votes BUY/SELL if >= 3/4 timeframes agree on direction.
    """

    AGENT_NAME = "trend"

    def run(self) -> AgentSignal:
        return AgentSignal.neutral(self.AGENT_NAME, "Trend agent is pure-math, not LLM-based.")

    def get_vote(
        self,
        market_trends: dict = None,
    ) -> AgentVote:
        market_trends = market_trends or self.market_trends
        
        if not market_trends:
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="HOLD",
                confidence=0.2,
                reasoning="No multi-timeframe trend data available.",
                weight=1.0,
            )

        tfs = ["1m", "15m", "1h", "1d", "1wk", "1mo"]
        directions = []
        for tf in tfs:
            if tf in market_trends:
                direction = market_trends[tf].get("trend_direction", "flat")
                directions.append(direction)
        
        if not directions:
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="HOLD",
                confidence=0.2,
                reasoning="Missing trend direction data in market_trends.",
                weight=1.0,
            )
            
        bullish_count = sum(1 for d in directions if d == "bullish")
        bearish_count = sum(1 for d in directions if d == "bearish")
        total_valid = len(directions)
        
        required_count = max(3, int(total_valid * 0.75))
        
        if bullish_count >= required_count:
            confidence = 0.5 + (0.5 * (bullish_count / total_valid))
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="BUY",
                confidence=confidence,
                reasoning=f"Trend aligned: {bullish_count}/{total_valid} timeframes are bullish.",
                weight=1.0,
            )
        elif bearish_count >= required_count:
            confidence = 0.5 + (0.5 * (bearish_count / total_valid))
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="SELL",
                confidence=confidence,
                reasoning=f"Trend aligned: {bearish_count}/{total_valid} timeframes are bearish.",
                weight=1.0,
            )
        else:
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="HOLD",
                confidence=0.5,
                reasoning=f"Trend conflict or ranging. Bullish: {bullish_count}, Bearish: {bearish_count}, Total: {total_valid}.",
                weight=1.0,
            )


# ─────────────────────────────────────────────
# VOLATILITY REGIME AGENT (Pure-math, no LLM)
# ─────────────────────────────────────────────

class VolatilityRegimeAgent(BaseAgent):
    """
    Classifies market regime as RANGING, TRENDING, or VOLATILE based on ATR z-score, ADX, and BB width.
    This was previously a silent gate in strategy.py, now formalised into the quorum.
    """
    AGENT_NAME = "regime"

    def run(self) -> AgentSignal:
        return AgentSignal.neutral(self.AGENT_NAME, "Regime agent is pure-math, not LLM-based.")

    def get_vote(
        self,
        raw_signal: str,
        market_trends: dict = None,
    ) -> AgentVote:
        market_trends = market_trends or self.market_trends
        
        # Use 15m or 1m timeframe for regime detection if available
        regime_data = market_trends.get("15m") or market_trends.get("1m") or {}
        
        if not regime_data:
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="HOLD",
                confidence=0.2,
                reasoning="No regime data available.",
                weight=1.0,
            )

        regime = regime_data.get("regime", "RANGING")
        adx = regime_data.get("adx", 0.0)
        atr_z = regime_data.get("atr_zscore", 0.0)
        
        if regime in ("TRENDING", "VOLATILE"):
            return AgentVote(
                agent=self.AGENT_NAME,
                vote="HOLD",
                confidence=min(1.0, 0.5 + abs(atr_z) * 0.1),
                reasoning=f"Market is {regime} (ADX={adx:.1f}, ATR_z={atr_z:.2f}). Mean reversion is risky.",
                weight=1.0,
            )
        else:
            return AgentVote(
                agent=self.AGENT_NAME,
                vote=raw_signal,
                confidence=0.7,
                reasoning=f"Market is {regime} (ADX={adx:.1f}, ATR_z={atr_z:.2f}). Favourable for mean reversion.",
                weight=1.0,
            )


# ─────────────────────────────────────────────
# RESEARCH BRIDGE AGENT (External signal injection)
# ─────────────────────────────────────────────

class ResearchBridgeAgent(BaseAgent):
    """
    Placeholder agent for the TradingAgents research framework integration.

    This agent does NOT run inline LLM calls. Its signal is produced
    asynchronously by `research_bridge.ResearchBridge.run_research()` and
    pushed into `SubAgentPool.latest_signals["research_framework"]` via
    `push_signal()` on a scheduled cycle (see `Fleet._check_research_bridge_cycle`).

    The class exists so:
      1. `AGENT_CLASSES["research_framework"]` resolves to a real class.
      2. `build_agent("research_framework", ...)` cannot crash if accidentally
         called (returns a neutral signal — deliberate() already skips inline
         refresh for this agent, see `panel_agents` loop guards).
    """

    AGENT_NAME = "research_framework"

    def run(self) -> AgentSignal:
        return AgentSignal.neutral(
            self.AGENT_NAME,
            reason=(
                "ResearchBridgeAgent is externally injected via "
                "ResearchBridge.run_research(); not run inline."
            ),
        )


# ─────────────────────────────────────────────
# AGENT FACTORY
# ─────────────────────────────────────────────

AGENT_CLASSES = {
    "sentiment": SentimentAgent,
    "macro": MacroAgent,
    "earnings": EarningsAgent,
    "technical": TechnicalAgent,
    "correlation": CorrelationAgent,
    "orderflow": OrderFlowAgent,
    "calendar": CalendarAgent,
    "research_framework": ResearchBridgeAgent,
    "risk_manager": RiskManagerAgent,
    "ict": ICTAgent,
    "cro": CROAgent,
    "trend": CrossTimeframeTrendAgent,
    "regime": VolatilityRegimeAgent,
}


def build_agent(
    agent_name: str,
    bot_id: str,
    symbol: str,
    openclaw_client: Optional[OpenAI],
    openclaw_model: str,
    ollama_base_url: str,
    ollama_model: str,
    market_trends: dict = None,
) -> Optional[BaseAgent]:
    cls = AGENT_CLASSES.get(agent_name)
    if cls is None:
        logger.warning(f"Unknown agent: {agent_name}")
        return None
    # Phase 4 §6.4 — per-agent Ollama model pool (heavier models for
    # complex agents like macro/cro, lightweight models for others).
    resolved_ollama = get_ollama_model(agent_name, fleet_default=ollama_model)
    return cls(
        bot_id=bot_id,
        symbol=symbol,
        openclaw_client=openclaw_client,
        openclaw_model=openclaw_model,
        ollama_base_url=ollama_base_url,
        ollama_model=resolved_ollama,
        market_trends=market_trends,
    )



# ─────────────────────────────────────────────
# DARWINIAN WEIGHT STORE
# ─────────────────────────────────────────────

class DarwinianWeightStore:
    """
    Tracks and updates per-agent Darwinian weights for one bot.

    Weight bounds: [FLOOR=0.3, CEILING=2.5], starting at 1.0.
    Update rule (applied after each closed trade):
      · Top-quartile agents (vote matched direction, trade profitable): weight *= 1.05
      · Bottom-quartile agents (vote opposed direction, trade was a loss): weight *= 0.95
      · Capped to [FLOOR, CEILING]
    """

    FLOOR   = 0.3
    CEILING = 2.5
    UP_FACTOR   = 1.05
    DOWN_FACTOR = 0.95

    # Agents that have static roles and should NOT be Darwinian-weighted.
    # These are gate agents (watchman, ict, correlation, trend, regime) and the
    # always-on risk manager — their fixed weights are encoded in their
    # AgentVote.weight at vote time and the panel weights table does not apply.
    EXCLUDED = {"watchman", "risk_manager", "ict", "correlation", "trend", "regime", "orderflow", "calendar"}

    def __init__(self, bot_id: str):
        self.bot_id = bot_id
        self._lock = threading.Lock()
        # Initial neutral weights for all panel agents
        self._weights: dict[str, float] = {
            "sentiment":          1.0,
            "macro":              1.0,
            "earnings":           1.5,
            "technical":          0.75,
            "cro":                1.5,
            "research_framework": 1.0,  # multiplies static panel weight of 2.0
        }
        # Outcome log for rolling Sharpe per agent
        # Each entry: {"agent": str, "voted": str, "trade_direction": str, "pnl": float}
        self._outcome_log: list[dict] = []
        self._logger = logging.getLogger(f"tradeclaw.darwin[{bot_id}]")
        self._load_from_db()

    def _load_from_db(self):
        """Load weights from PostgreSQL on init (fire-and-forget on the main event loop)."""
        try:
            import postgres_store
            loop = _main_event_loop
            if loop and loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    postgres_store.load_darwinian_weights(self.bot_id), loop
                )
                try:
                    saved = future.result(timeout=5)
                    if saved:
                        with self._lock:
                            self._weights.update(saved)
                        self._logger.info(f"Loaded Darwinian weights from Postgres: {saved}")
                except Exception as e:
                    self._logger.warning(f"Darwinian weights load timed out or failed: {e}")
        except Exception as e:
            self._logger.warning(f"Failed to load weights from DB: {e}")

    def _save_to_db(self):
        """Persist current weights to PostgreSQL (fire-and-forget)."""
        try:
            import postgres_store
            with self._lock:
                weights = dict(self._weights)
            loop = _main_event_loop
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    postgres_store.save_darwinian_weights(self.bot_id, weights), loop
                )
        except Exception as e:
            self._logger.warning(f"Failed to save weights to DB: {e}")

    def get_weight(self, agent_name: str) -> float:
        """Return the current Darwinian weight for an agent (default 1.0)."""
        if agent_name in self.EXCLUDED:
            return 1.0
        with self._lock:
            return self._weights.get(agent_name, 1.0)

    def record_outcome(self, votes: list[dict], trade_direction: str, pnl: float):
        """
        Called after a trade closes. Attributes the outcome to each agent
        that voted before the entry.
        """
        with self._lock:
            for vote_dict in votes:
                agent = vote_dict.get("agent", "")
                if agent in self.EXCLUDED:
                    continue
                self._outcome_log.append({
                    "agent":           agent,
                    "voted":           vote_dict.get("vote", "HOLD"),
                    "trade_direction": trade_direction,
                    "pnl":             pnl,
                    "ts":              datetime.now(timezone.utc).isoformat(),
                })
            # Keep the log bounded (last 200 outcomes)
            self._outcome_log = self._outcome_log[-200:]

    def daily_update(self):
        """
        Apply one round of Darwinian selection.
        """
        import numpy as np

        with self._lock:
            outcomes = list(self._outcome_log)

        if not outcomes:
            self._logger.info("No outcomes to process for Darwinian update.")
            return

        # Compute per-agent scores
        agent_scores: dict[str, float] = {}
        agents_in_log = set(o["agent"] for o in outcomes)
        
        for agent in agents_in_log:
            agent_outcomes = [o for o in outcomes if o["agent"] == agent][-60:]
            if len(agent_outcomes) < 3:
                continue

            returns = []
            for o in agent_outcomes:
                voted_correctly = (o["voted"] == o["trade_direction"])
                # Simplistic reward/penalty based on PnL
                signed_pnl = o["pnl"] if voted_correctly else -o["pnl"]
                returns.append(signed_pnl)

            if len(returns) < 2:
                continue
            
            mean_r = float(np.mean(returns))
            std_r  = float(np.std(returns))
            
            # Sharpe-like score: reward higher mean and lower variance.
            # Use a small epsilon to avoid division by zero while rewarding consistency.
            agent_scores[agent] = mean_r / (std_r + 1e-6)

        if len(agent_scores) < 2:
            self._logger.info(f"Insufficient data to rank agents (scored: {list(agent_scores.keys())})")
            return

        sorted_agents = sorted(agent_scores.keys(), key=lambda a: agent_scores[a])
        n = len(sorted_agents)
        top_cutoff    = max(1, n // 4)
        bottom_cutoff = max(1, n // 4)

        top_agents    = set(sorted_agents[-top_cutoff:])
        bottom_agents = set(sorted_agents[:bottom_cutoff])

        with self._lock:
            for agent in self._weights:
                if agent in self.EXCLUDED:
                    continue
                old_w = self._weights[agent]
                if agent in top_agents:
                    self._weights[agent] = min(self.CEILING, self._weights[agent] * self.UP_FACTOR)
                    self._logger.info(
                        f"[Darwin] {agent} ↑ {self._weights[agent]:.3f} (top quartile)",
                        extra={
                            "event": "darwin_update",
                            "agent": agent,
                            "direction": "up",
                            "old_weight": round(old_w, 4),
                            "new_weight": round(self._weights[agent], 4),
                        },
                    )
                elif agent in bottom_agents:
                    self._weights[agent] = max(self.FLOOR, self._weights[agent] * self.DOWN_FACTOR)
                    self._logger.info(
                        f"[Darwin] {agent} ↓ {self._weights[agent]:.3f} (bottom quartile)",
                        extra={
                            "event": "darwin_update",
                            "agent": agent,
                            "direction": "down",
                            "old_weight": round(old_w, 4),
                            "new_weight": round(self._weights[agent], 4),
                        },
                    )

        # ── Exponential decay (Phase 3 §4.2) ─────────────────────────────
        # All non-excluded agents regress toward 1.0 each cycle. Applied AFTER
        # the quartile selection so high-performers decay slightly even after
        # being bumped, preventing permanent ceiling/floor lock-in for agents
        # that aren't currently producing trade outcomes.
        _DECAY_RATE = 0.02
        with self._lock:
            for _agent, _w in list(self._weights.items()):
                if _agent in self.EXCLUDED:
                    continue
                # Weighted-mean decay toward 1.0: w' = w + DECAY_RATE * (1.0 - w)
                _new = _w + _DECAY_RATE * (1.0 - _w)
                self._weights[_agent] = max(self.FLOOR, min(self.CEILING, _new))

        self._save_to_db()

    def get_all_weights(self) -> dict[str, float]:
        with self._lock:
            return dict(self._weights)

    def set_weight(self, agent: str, value: float) -> float:
        """
        Manually override an agent's Darwinian weight (Phase 3 §5.3).

        Used by the operator REST endpoint `PUT /fleet/bot/{id}/agents/weights`.
        Clamps the supplied value to [FLOOR, CEILING] and persists to Postgres.
        Returns the actual stored weight after clamping.

        Excluded gate agents (watchman, ict, correlation, etc.) refuse override —
        their weights are baked into their AgentVote.weight at vote time.
        """
        if agent in self.EXCLUDED:
            raise ValueError(
                f"Agent '{agent}' is excluded from Darwinian weighting "
                f"(gate agents use fixed weights at vote time)."
            )
        try:
            v = float(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"weight must be numeric: {e}")
        v = max(self.FLOOR, min(self.CEILING, v))
        with self._lock:
            self._weights[agent] = v
        self._save_to_db()
        self._logger.info(
            f"[Darwin] {agent} weight manually set to {v:.3f}",
            extra={"event": "darwin_manual_override", "agent": agent, "new_weight": v},
        )
        return v


# ─────────────────────────────────────────────
# SUB-AGENT POOL
# ─────────────────────────────────────────────

class SubAgentPool:
    """
    Manages a bot's pool of sub-agents. Runs them in parallel via ThreadPoolExecutor.
    Results are stored and available to the AI Brain before each evolution cycle.
    """

    def __init__(
        self,
        bot_id: str,
        symbol: str,
        enabled_agents: list[str],
        openclaw_client: Optional[OpenAI],
        openclaw_model: str,
        ollama_base_url: str = "http://localhost:11434",
        ollama_model: str = "gemma4:e4b",
        interval_minutes: int = 15,
    ):
        self.bot_id = bot_id
        self.symbol = symbol
        self.enabled_agents = enabled_agents
        self.interval_minutes = interval_minutes

        self._openclaw_client = openclaw_client
        self._openclaw_model = openclaw_model
        self._ollama_base_url = ollama_base_url
        self._ollama_model = ollama_model

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._executor = ThreadPoolExecutor(
            max_workers=len(enabled_agents) or 1,
            thread_name_prefix=f"agent-{bot_id}",
        )

        # Latest signals — keyed by agent name (for AI Brain backward compat)
        self.latest_signals: dict[str, AgentSignal] = {}
        self.last_run_at: Optional[str] = None
        self.total_runs: int = 0

        # Latest deliberation result — persisted for the API endpoint
        self.last_deliberation: Optional[TradeDecision] = None

        # Timestamp per agent's last vote (for cache staleness checks)
        self._vote_timestamps: dict[str, float] = {}

        self._logger = logging.getLogger(f"tradeclaw.agents.pool[{bot_id}]")
        self._darwin = DarwinianWeightStore(bot_id)

        # LangGraph integration — deliberation event stream for Situation Room UI.
        # Events are put here during graph execution and drained by the WS broadcast loop.
        self._event_queue: _stdlib_queue.Queue = _stdlib_queue.Queue(maxsize=200)
        self._deliberation_graph = None   # Lazily initialised on first deliberate() call

        # Local cache of multi-timeframe trends for the background loop
        self.market_trends: dict = {}

        # Phase 3 §9.1 — Raw multi-timeframe DataFrames pushed by FleetOrchestrator
        # after MarketDataAggregator.process_symbol. In-process only; never
        # serialised or persisted. Consumed by agents whose `dataframes` attr
        # is set at build time (see build_agent + deliberate() correlation gate).
        self.market_data_frames: dict = {}

        # Phase 4 §7.3 — Per-bot event loop (injected by fleet after bot loop starts).
        # If set, _persist_deliberation and Darwinian weight persistence will use
        # this loop instead of contending on the fleet-level _main_event_loop.
        self._bot_loop: Optional[Any] = None

    def set_bot_loop(self, loop):
        """Inject the bot's dedicated event loop (Phase 4 §7.3)."""
        self._bot_loop = loop

    def start(self):
        """Start the background agent polling loop."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"sub-agents-{self.bot_id}",
        )
        self._thread.start()
        
        # Initial research fetch (pull from PostgreSQL cache)
        self._fetch_cached_research()
        
        self._logger.info(f"SubAgentPool started. Agents: {self.enabled_agents}")

    def _fetch_cached_research(self):
        """Pull the latest research signal from PostgreSQL if available."""
        if "research_framework" not in (self.enabled_agents or []):
            return
            
        loop = _main_event_loop
        if loop and loop.is_running():
            try:
                from research_bridge import research_bridge
                # run_research(force=False) uses cache
                future = asyncio.run_coroutine_threadsafe(
                    research_bridge.run_research(self.symbol), loop
                )
                # Short timeout, we don't want to block startup too long
                signal = future.result(timeout=10)
                if signal and signal.confidence > 0:
                    self.push_signal(signal)
            except Exception as e:
                self._logger.debug(f"Initial research fetch failed: {e}")

    def stop(self):
        """Stop the background loop and executor."""
        self._stop_event.set()
        self._executor.shutdown(wait=False)
        self._logger.info("SubAgentPool stopped")

    def _get_deliberation_graph(self):
        """Lazily initialise and return the LangGraph deliberation graph (or None)."""
        if self._deliberation_graph is None:
            try:
                from deliberation_graph import DeliberationGraph  # noqa: PLC0415
                self._deliberation_graph = DeliberationGraph(pool=self)
                self._logger.info("LangGraph deliberation graph initialised")
            except Exception as _e:
                self._logger.info(f"LangGraph unavailable — using direct deliberation: {_e}")
                self._deliberation_graph = False  # Sentinel: tried and failed, don't retry
        return self._deliberation_graph if self._deliberation_graph else None

    def update_market_trends(self, trends: dict):
        """Update the local cache of multi-timeframe trends (pushed from FleetManager)."""
        with self._lock:
            self.market_trends = trends or {}

    def update_market_data_frames(self, frames: dict) -> None:
        """
        Update in-process DataFrames (Phase 3 §9.1).

        Called by FleetOrchestrator after MarketDataAggregator.process_symbol().
        Stored separately from `market_trends` (which is JSON-friendly) because
        DataFrames are not serialisable and must not leak into WS payloads.
        """
        with self._lock:
            self.market_data_frames = frames or {}

    def push_signal(self, signal: AgentSignal):
        """
        Manually inject a signal (e.g. from the ResearchBridge).
        This allows high-latency research results to be injected into the 
        real-time pool for deliberation.
        """
        with self._lock:
            self.latest_signals[signal.agent] = signal
            self._vote_timestamps[signal.agent] = time.time()
        self._logger.info(f"Signal pushed for agent: {signal.agent} (sentiment={signal.sentiment})")

    def run_now(self) -> dict[str, AgentSignal]:
        """Run all agents immediately and return their signals."""
        return self._run_agents()

    def get_latest_signals(self) -> dict[str, AgentSignal]:
        """Thread-safe snapshot of latest agent signals."""
        with self._lock:
            return dict(self.latest_signals)

    def get_aggregate_sentiment(self) -> dict:
        """
        Compute a weighted aggregate sentiment from all agent signals.
        Returns: {"score": float, "confidence": float, "breakdown": dict}
        """
        with self._lock:
            signals = list(self.latest_signals.values())

        if not signals:
            return {"score": 0.0, "confidence": 0.0, "breakdown": {}}

        # Weight by confidence
        total_weight = sum(s.confidence for s in signals)
        if total_weight == 0:
            return {"score": 0.0, "confidence": 0.0, "breakdown": {}}

        weighted_score = sum(s.sentiment * s.confidence for s in signals) / total_weight
        avg_confidence = total_weight / len(signals)

        breakdown = {
            s.agent: {
                "sentiment": round(s.sentiment, 3),
                "confidence": round(s.confidence, 3),
                "reasoning": s.reasoning[:120],
            }
            for s in signals
        }

        return {
            "score": round(weighted_score, 3),
            "confidence": round(avg_confidence, 3),
            "breakdown": breakdown,
        }

    # ── MAS Deliberation ──────────────────────────────────────────────

    def deliberate(
        self,
        raw_signal: str,            # "BUY" | "SELL" from the Strategist
        requested_qty: float,
        equity: float,
        daily_pnl: float,
        starting_equity: float,
        max_daily_drawdown_pct: float,
        recent_trades: list,
        survival_state: str,
        signal_price: float = 0.0,
        price_history=None,         # deque of price points for WatchmanAgent
        market_trends: dict = None, # Local trend summaries (1m, 15m, 1h, 1d, etc.)
        vote_cache_ttl: int = 1800, # seconds; cached LLM votes older than this are refreshed
    ) -> TradeDecision:
        """
        The expert team debate.  Runs all agents and determines whether to
        approve the trade, with what qty and order urgency.

        Protocol:
          1. Any VETO from any agent → blocked
          2. ≥ 3/5 panel agents agree on direction → quorum
          3. Weighted score ≥ 0.2 → confidence gate
          4. RiskManagerAgent approves qty

        Agent weights:
          sentiment=1.0, macro=1.0, earnings=1.5, technical=0.75, watchman=1.25
        """
        if raw_signal not in ("BUY", "SELL"):
            return TradeDecision(
                approved=False,
                signal=raw_signal,
                approved_qty=0,
                order_urgency="LOW",
                quorum_score=0.0,
                reasoning="No directional signal from Strategist.",
            )

        # ── LangGraph path (when available) ───────────────────────────
        # Attempt to route deliberation through the typed StateGraph which
        # provides event streaming to the Situation Room WS clients.
        # Falls back to the direct path below on any failure.
        _loop = _main_event_loop
        _graph = self._get_deliberation_graph()
        if _graph and _loop and _loop.is_running():
            try:
                _state = {
                    "bot_id": self.bot_id,
                    "raw_signal": raw_signal,
                    "requested_qty": requested_qty,
                    "equity": equity,
                    "daily_pnl": daily_pnl,
                    "starting_equity": starting_equity,
                    "max_daily_drawdown_pct": max_daily_drawdown_pct,
                    "recent_trades": recent_trades,
                    "survival_state": survival_state,
                    "signal_price": signal_price,
                    "vote_cache_ttl": vote_cache_ttl,
                    "enabled_agents": list(self.enabled_agents),
                    "market_trends": market_trends or {},
                }
                _fut = asyncio.run_coroutine_threadsafe(
                    _graph.arun(_state, event_queue=self._event_queue,
                                price_history=price_history,
                                market_trends=market_trends),
                    _loop,
                )
                _decision = _fut.result(timeout=120)
                if _decision is not None:
                    with self._lock:
                        self.last_deliberation = _decision
                    self._persist_deliberation(_decision)
                    return _decision
            except Exception as _ge:
                self._logger.warning(
                    f"LangGraph deliberation error: {_ge} — falling back to direct path"
                )

        votes: list[AgentVote] = []
        veto_agents: list[str] = []

        # ── Calendar Gate (Phase 4 §3.4) ───────────────────────────────
        # FIRST gate — economic calendar VETO blocks all entries within ±30
        # min of high-impact events (FOMC, NFP, CPI, etc.). No other analysis
        # should run when the calendar prohibits entry.
        if "calendar" in self.enabled_agents:
            try:
                cal_agent = CalendarAgent(
                    bot_id=self.bot_id, symbol=self.symbol,
                    openclaw_client=self._openclaw_client,
                    openclaw_model=self._openclaw_model,
                    ollama_base_url=self._ollama_base_url,
                    ollama_model=self._ollama_model,
                )
                cal_vote = cal_agent.get_vote()
                votes.append(cal_vote)
                if cal_vote.vote == "VETO":
                    veto_agents.append(cal_vote.agent)
            except Exception as e:
                self._logger.warning(f"CalendarAgent vote error: {e}")

        # ── Watchman (real-time gate, always fresh) ────────────────────
        try:
            watchman = WatchmanAgent(
                bot_id=self.bot_id, symbol=self.symbol,
                openclaw_client=self._openclaw_client,
                openclaw_model=self._openclaw_model,
                ollama_base_url=self._ollama_base_url,
                ollama_model=self._ollama_model,
            )
            w_vote = watchman.get_vote(price_history=price_history)
            votes.append(w_vote)
            if w_vote.vote == "VETO":
                veto_agents.append(w_vote.agent)
        except Exception as e:
            self._logger.warning(f"WatchmanAgent vote error: {e}")

        # ── ICT Smart Money (pure-math, always fresh, no LLM) ─────────
        if "ict" in self.enabled_agents:
            try:
                ict_agent = ICTAgent(
                    bot_id=self.bot_id, symbol=self.symbol,
                    openclaw_client=self._openclaw_client,
                    openclaw_model=self._openclaw_model,
                    ollama_base_url=self._ollama_base_url,
                    ollama_model=self._ollama_model,
                )
                ict_vote = ict_agent.get_vote(price_history=price_history)
                votes.append(ict_vote)
            except Exception as e:
                self._logger.warning(f"ICTAgent vote error: {e}")

        # ── Cross-Timeframe Trend (pure-math, always fresh, no LLM) ───
        if "trend" in self.enabled_agents:
            try:
                trend_agent = CrossTimeframeTrendAgent(
                    bot_id=self.bot_id, symbol=self.symbol,
                    openclaw_client=self._openclaw_client,
                    openclaw_model=self._openclaw_model,
                    ollama_base_url=self._ollama_base_url,
                    ollama_model=self._ollama_model,
                    market_trends=market_trends or self.market_trends,
                )
                trend_vote = trend_agent.get_vote()
                votes.append(trend_vote)
            except Exception as e:
                self._logger.warning(f"TrendAgent vote error: {e}")

        # ── Volatility Regime (pure-math, always fresh, no LLM) ───────
        if "regime" in self.enabled_agents:
            try:
                regime_agent = VolatilityRegimeAgent(
                    bot_id=self.bot_id, symbol=self.symbol,
                    openclaw_client=self._openclaw_client,
                    openclaw_model=self._openclaw_model,
                    ollama_base_url=self._ollama_base_url,
                    ollama_model=self._ollama_model,
                    market_trends=market_trends or self.market_trends,
                )
                regime_vote = regime_agent.get_vote(raw_signal=raw_signal)
                votes.append(regime_vote)
            except Exception as e:
                self._logger.warning(f"RegimeAgent vote error: {e}")

        # ── Correlation Gate (Phase 3 §3.1) ─────────────────────────────
        # Pure-stats inter-market correlation check. Issues a VETO when ≥2
        # historical correlations break (e.g. EURUSD ↔ DXY positive). Acts
        # as a gate like Watchman/ICT — NOT a panel voter — with weight 1.25
        # already encoded in the AgentVote returned by get_vote().
        if "correlation" in self.enabled_agents:
            try:
                corr_agent = CorrelationAgent(
                    bot_id=self.bot_id, symbol=self.symbol,
                    openclaw_client=self._openclaw_client,
                    openclaw_model=self._openclaw_model,
                    ollama_base_url=self._ollama_base_url,
                    ollama_model=self._ollama_model,
                    market_trends=market_trends or self.market_trends,
                )
                # Inject DataFrames if available (Phase 3 §9.1)
                if hasattr(self, "market_data_frames"):
                    corr_agent.dataframes = self.market_data_frames
                corr_vote = corr_agent.get_vote()
                votes.append(corr_vote)
                if corr_vote.vote == "VETO":
                    veto_agents.append(corr_vote.agent)
            except Exception as e:
                self._logger.warning(f"CorrelationAgent vote error: {e}")

        # ── Order Flow Gate (Phase 4 §3.2) ─────────────────────────────
        # Pure-math tick-level order flow analysis (cumulative delta divergence
        # + VWAP displacement). Flags institutional distribution (VETO on BUY)
        # and accumulation (strong HOLD). Weight 1.5 baked into the AgentVote.
        if "orderflow" in self.enabled_agents:
            try:
                of_agent = OrderFlowAgent(
                    bot_id=self.bot_id, symbol=self.symbol,
                    openclaw_client=self._openclaw_client,
                    openclaw_model=self._openclaw_model,
                    ollama_base_url=self._ollama_base_url,
                    ollama_model=self._ollama_model,
                    market_trends=market_trends or self.market_trends,
                )
                of_vote = of_agent.get_vote(
                    raw_signal=raw_signal,
                    price_history=price_history,
                )
                votes.append(of_vote)
                if of_vote.vote == "VETO":
                    veto_agents.append(of_vote.agent)
            except Exception as e:
                self._logger.warning(f"OrderFlowAgent vote error: {e}")

        # ── PHASE 3: Macro Regime Pre-Filter ────────────────────────────
        # Fast-path veto before running the full LLM panel: if the MacroAgent's
        # latest read shows a strongly RISK_OFF regime with high confidence,
        # BUY entries are blocked immediately (saves 3 extra LLM calls).
        # SELL / short entries are NOT blocked — macro tailwind supports them.
        _MACRO_VETO_SENTIMENT  = -0.6
        _MACRO_VETO_CONFIDENCE = 0.65

        if "macro" in self.enabled_agents and raw_signal == "BUY":
            with self._lock:
                _macro_cached = self.latest_signals.get("macro")
            _macro_age = time.time() - self._vote_timestamps.get("macro", 0)

            if _macro_cached is None or _macro_age > vote_cache_ttl:
                try:
                    _m_agent = build_agent(
                        agent_name="macro", bot_id=self.bot_id, symbol=self.symbol,
                        openclaw_client=self._openclaw_client,
                        openclaw_model=self._openclaw_model,
                        ollama_base_url=self._ollama_base_url,
                        ollama_model=self._ollama_model,
                        market_trends=market_trends or self.market_trends,
                    )
                    if _m_agent:
                        _macro_cached = _m_agent.run()
                        with self._lock:
                            self.latest_signals["macro"] = _macro_cached
                        self._vote_timestamps["macro"] = time.time()
                except Exception as _e:
                    self._logger.warning(f"Macro pre-filter refresh failed: {_e}")

            if (
                _macro_cached is not None
                and _macro_cached.sentiment < _MACRO_VETO_SENTIMENT
                and _macro_cached.confidence > _MACRO_VETO_CONFIDENCE
            ):
                _macro_veto_vote = AgentVote(
                    agent="macro",
                    vote="VETO",
                    confidence=_macro_cached.confidence,
                    reasoning=(
                        f"MACRO RISK_OFF PRE-FILTER: sentiment={_macro_cached.sentiment:.2f} "
                        f"(threshold {_MACRO_VETO_SENTIMENT}). {_macro_cached.reasoning[:150]}"
                    ),
                    weight=2.0,
                    veto_reason=(
                        f"Macro regime RISK_OFF (sentiment={_macro_cached.sentiment:.2f})"
                    ),
                )
                votes.append(_macro_veto_vote)
                decision = TradeDecision(
                    approved=False,
                    signal=raw_signal,
                    approved_qty=0,
                    order_urgency="LOW",
                    quorum_score=0.0,
                    votes=[v.to_dict() for v in votes],
                    veto_agents=["macro"],
                    reasoning=_macro_veto_vote.reasoning,
                )
                with self._lock:
                    self.last_deliberation = decision
                self._logger.warning(
                    f"[{self.bot_id}] MACRO RISK_OFF PRE-FILTER — {_macro_veto_vote.reasoning[:100]}",
                    extra={
                        "event": "macro_risk_off_veto",
                        "bot_id": self.bot_id,
                        "symbol": self.symbol,
                        "signal": raw_signal,
                        "macro_sentiment": round(_macro_cached.sentiment, 3),
                        "macro_confidence": round(_macro_cached.confidence, 3),
                    },
                )
                self._persist_deliberation(decision)
                return decision

        # ── LLM panel votes (use cached results, refresh if stale) ────
        panel_agents = ["sentiment", "macro", "earnings", "technical", "research_framework"]
        
        # Static base weights × live Darwinian multipliers
        _static = {"sentiment": 1.0, "macro": 1.0, "earnings": 1.5, "technical": 0.75, "research_framework": 2.0}

        with self._lock:
            current_signals = dict(self.latest_signals)
            current_timestamps = dict(self._vote_timestamps)

        failed_agents: list[str] = []  # Track agents that failed to respond

        for agent_name in panel_agents:
            if agent_name not in self.enabled_agents and agent_name != "research_framework":
                # Only check enabled_agents for built-in agents
                continue

            signal = current_signals.get(agent_name)
            age = time.time() - current_timestamps.get(agent_name, 0)

            # Refresh if stale or missing (only for built-in agents, research_framework is updated externally)
            if (signal is None or age > vote_cache_ttl) and agent_name != "research_framework":
                try:
                    agent = build_agent(
                        agent_name=agent_name,
                        bot_id=self.bot_id,
                        symbol=self.symbol,
                        openclaw_client=self._openclaw_client,
                        openclaw_model=self._openclaw_model,
                        ollama_base_url=self._ollama_base_url,
                        ollama_model=self._ollama_model,
                        market_trends=market_trends or self.market_trends,
                    )
                    if agent:
                        signal = agent.run()
                        with self._lock:
                            self.latest_signals[agent_name] = signal
                        self._vote_timestamps[agent_name] = time.time()
                except Exception as e:
                    self._logger.warning(f"[{agent_name}] refresh failed: {e}")
                    failed_agents.append(agent_name)

            if signal is None:
                failed_agents.append(agent_name)
                continue

            # Agents with confidence=0 are effectively "no data" / failed —
            # treat them as abstentions rather than HOLD votes that block quorum
            if signal.confidence < 0.05:
                self._logger.debug(
                    f"[{agent_name}] abstaining (confidence={signal.confidence:.2f}, "
                    f"reason={signal.reasoning[:80]})"
                )
                continue  # Skip — don't add a vote that would dilute quorum

            # Translate AgentSignal.sentiment to a directional vote
            if signal.confidence < 0.1:
                vote_str = "HOLD"
            elif signal.sentiment > 0.15:
                vote_str = "BUY"
            elif signal.sentiment < -0.15:
                vote_str = "SELL"
            else:
                vote_str = "HOLD"

            # Earnings agent: extreme negative → VETO
            if agent_name == "earnings" and signal.sentiment < -0.7 and signal.confidence > 0.6:
                vote_str = "VETO"

            # Macro agent: hard veto for BUY signals if regime is RISK_OFF
            if agent_name == "macro" and raw_signal == "BUY" and signal.sentiment < -0.6 and signal.confidence > 0.6:
                vote_str = "VETO"
                signal.reasoning = f"HARD VETO (RISK_OFF): {signal.reasoning}"

            agent_vote = AgentVote(
                agent=agent_name,
                vote=vote_str,
                confidence=signal.confidence,
                reasoning=signal.reasoning[:200],
                weight=_static.get(agent_name, 1.0),
                darwinian_weight=self._darwin.get_weight(agent_name),
                veto_reason=signal.reasoning[:120] if vote_str == "VETO" else None,
            )
            votes.append(agent_vote)
            if vote_str == "VETO":
                veto_agents.append(agent_name)

        # ── CRO Adversarial Review (Gating) ───────────────────────────
        if "cro" in self.enabled_agents and not veto_agents:
            try:
                cro_agent = CROAgent(
                    bot_id=self.bot_id, symbol=self.symbol,
                    openclaw_client=self._openclaw_client,
                    openclaw_model=self._openclaw_model,
                    ollama_base_url=self._ollama_base_url,
                    ollama_model=self._ollama_model,
                )
                with self._lock:
                    macro_sig = self.latest_signals.get("macro")
                
                cro_vote = cro_agent.get_vote(
                    raw_signal=raw_signal,
                    symbol=self.symbol,
                    panel_votes=votes,
                    macro_signal=macro_sig,
                    price_history=price_history,
                )
                # Apply live Darwinian weight
                cro_vote.darwinian_weight = self._darwin.get_weight("cro")
                votes.append(cro_vote)
                if cro_vote.vote == "VETO":
                    veto_agents.append(cro_vote.agent)
            except Exception as e:
                self._logger.warning(f"CROAgent vote error: {e}")

        # ── Deliberation scorecard ────────────────────────────────────
        self._logger.info(
            f"[{self.bot_id}] ┌─ DELIBERATION on {raw_signal} ({'%d' % len(votes)} agents) ─────────"
        )
        for v in votes:
            arrow = "✓" if v.vote == raw_signal else ("✗ VETO" if v.vote == "VETO" else f"~ {v.vote}")
            dw = getattr(v, "darwinian_weight", 1.0)
            self._logger.info(
                f"[{self.bot_id}] │ {v.agent:<14} [{arrow}]  conf={v.confidence:.0%}"
                f"  w={v.weight:.2f}×{dw:.2f}  {v.reasoning[:80]}",
                extra={
                    "event": "agent_vote",
                    "bot_id": self.bot_id,
                    "symbol": self.symbol,
                    "raw_signal": raw_signal,
                    "agent": v.agent,
                    "vote": v.vote,
                    "confidence": round(v.confidence, 3),
                    "weight": round(v.weight, 3),
                    "darwinian_weight": round(dw, 3),
                },
            )
        self._logger.info(f"[{self.bot_id}] └──────────────────────────────────────────────────────")

        # ── VETO check ────────────────────────────────────────────────
        if veto_agents:
            decision = TradeDecision(
                approved=False,
                signal=raw_signal,
                approved_qty=0,
                order_urgency="LOW",
                quorum_score=0.0,
                votes=[v.to_dict() for v in votes],
                veto_agents=veto_agents,
                reasoning=f"VETO issued by: {', '.join(veto_agents)}",
            )
            with self._lock:
                self.last_deliberation = decision
            self._logger.warning(
                f"[{self.bot_id}] DELIBERATION VETO — {decision.reasoning}",
                extra={
                    "event": "deliberation_veto",
                    "bot_id": self.bot_id,
                    "symbol": self.symbol,
                    "signal": raw_signal,
                    "veto_agents": list(veto_agents),
                    "vote_count": len(votes),
                },
            )
            # Phase 3 §5.3 — persist deliberation to strategy_contexts
            self._persist_deliberation(decision)
            return decision

        # ── Degraded-quorum safety check ─────────────────────────────────
        # If more than half the enabled panel agents failed, we cannot trust
        # the quorum result — refuse the trade to prevent acting on
        # incomplete intelligence.
        enabled_panel_count = sum(1 for a in panel_agents if a in self.enabled_agents)
        if enabled_panel_count > 0 and len(failed_agents) > enabled_panel_count / 2:
            decision = TradeDecision(
                approved=False,
                signal=raw_signal,
                approved_qty=0,
                order_urgency="LOW",
                quorum_score=0.0,
                votes=[v.to_dict() for v in votes],
                veto_agents=[],
                reasoning=(
                    f"Quorum degraded: {len(failed_agents)}/{enabled_panel_count} "
                    f"panel agents failed ({', '.join(failed_agents)}). "
                    f"Trade blocked for safety."
                ),
            )
            with self._lock:
                self.last_deliberation = decision
            self._logger.warning(
                f"[{self.bot_id}] DELIBERATION DEGRADED — {decision.reasoning}",
                extra={
                    "event": "deliberation_degraded",
                    "bot_id": self.bot_id,
                    "symbol": self.symbol,
                    "signal": raw_signal,
                    "failed_agents": list(failed_agents),
                    "enabled_panel_count": enabled_panel_count,
                },
            )
            self._persist_deliberation(decision)
            return decision

        # ── Quorum calculation (non-Risk / non-Watchman / non-ICT direction votes) ─
        panel_votes = [v for v in votes if v.agent not in ("risk_manager", "watchman", "ict")]

        agree_count = sum(1 for v in panel_votes if v.vote == raw_signal)
        total_panel = len(panel_votes)

        # Safety: if ALL panel agents abstained (LLM outage), block the trade.
        # Operating without any intelligence is worse than missing a signal.
        if total_panel == 0:
            _decision = TradeDecision(
                approved=False,
                signal=raw_signal,
                approved_qty=0,
                order_urgency="LOW",
                quorum_score=0.0,
                votes=[v.to_dict() for v in votes],
                veto_agents=[],
                reasoning=(
                    "All panel agents unavailable (Gemini exhausted + Ollama unreachable). "
                    "Trade blocked — no intelligence to act on."
                ),
            )
            with self._lock:
                self.last_deliberation = _decision
            self._logger.warning(
                f"[{self.bot_id}] DELIBERATION BLOCKED — all panel agents unavailable (LLM outage)",
                extra={
                    "event": "deliberation_blocked_llm_outage",
                    "bot_id": self.bot_id,
                    "symbol": self.symbol,
                    "signal": raw_signal,
                },
            )
            self._persist_deliberation(_decision)
            return _decision

        # Weighted net-score using effective weight (static × Darwinian)
        total_weight = sum(v.weight * v.darwinian_weight for v in panel_votes) or 1.0
        weighted_score = sum(
            (v.weight * v.darwinian_weight) * v.confidence
            * (1 if v.vote == raw_signal else -1 if v.vote not in ("HOLD", "VETO") else 0)
            for v in panel_votes
        ) / total_weight

        # Score must clear 0.25 (slightly tighter than old 0.2 to compensate for
        # removing the raw agree_count gate — weights now do that work)
        quorum_met = weighted_score >= 0.25

        self._logger.info(
            f"[{self.bot_id}] QUORUM: {agree_count}/{total_panel} agree | "
            f"weighted_score={weighted_score:.3f} (need ≥0.25) | {'PASS' if quorum_met else 'FAIL'}"
        )

        if not quorum_met:
            decision = TradeDecision(
                approved=False,
                signal=raw_signal,
                approved_qty=0,
                order_urgency="LOW",
                quorum_score=round(weighted_score, 3),
                votes=[v.to_dict() for v in votes],
                veto_agents=[],
                reasoning=(
                    f"Quorum failed: {agree_count}/{total_panel} agents agree, "
                    f"weighted_score={weighted_score:.3f}."
                ),
            )
            with self._lock:
                self.last_deliberation = decision
            self._logger.info(
                f"[{self.bot_id}] DELIBERATION NO-QUORUM — {decision.reasoning}",
                extra={
                    "event": "deliberation_no_quorum",
                    "bot_id": self.bot_id,
                    "symbol": self.symbol,
                    "signal": raw_signal,
                    "agree_count": agree_count,
                    "total_panel": total_panel,
                    "quorum_score": round(weighted_score, 3),
                },
            )
            self._persist_deliberation(decision)
            return decision

        # ── Risk Manager final approval ────────────────────────────────
        try:
            risk_agent = RiskManagerAgent(
                bot_id=self.bot_id, symbol=self.symbol,
                openclaw_client=self._openclaw_client,
                openclaw_model=self._openclaw_model,
                ollama_base_url=self._ollama_base_url,
                ollama_model=self._ollama_model,
            )
            risk_vote, approved_qty = risk_agent.get_vote(
                signal=raw_signal,
                requested_qty=requested_qty,
                equity=equity,
                daily_pnl=daily_pnl,
                starting_equity=starting_equity,
                max_daily_drawdown_pct=max_daily_drawdown_pct,
                recent_trades=recent_trades,
                survival_state=survival_state,
            )
            votes.append(risk_vote)
            if risk_vote.vote == "VETO":
                decision = TradeDecision(
                    approved=False,
                    signal=raw_signal,
                    approved_qty=0,
                    order_urgency="LOW",
                    quorum_score=round(weighted_score, 3),
                    votes=[v.to_dict() for v in votes],
                    veto_agents=["risk_manager"],
                    reasoning=f"Risk Manager VETO: {risk_vote.veto_reason}",
                )
                with self._lock:
                    self.last_deliberation = decision
                self._logger.warning(
                    f"[{self.bot_id}] DELIBERATION RISK VETO — {risk_vote.veto_reason}",
                    extra={
                        "event": "deliberation_risk_veto",
                        "bot_id": self.bot_id,
                        "symbol": self.symbol,
                        "signal": raw_signal,
                        "veto_reason": risk_vote.veto_reason,
                        "quorum_score": round(weighted_score, 3),
                    },
                )
                self._persist_deliberation(decision)
                return decision
        except Exception as e:
            self._logger.error(f"RiskManagerAgent error: {e} — blocking trade for safety")
            decision = TradeDecision(
                approved=False,
                signal=raw_signal,
                approved_qty=0,
                order_urgency="LOW",
                quorum_score=round(weighted_score, 3),
                votes=[v.to_dict() for v in votes],
                veto_agents=["risk_manager"],
                reasoning=f"Risk Manager unavailable: {e}. Trade blocked for safety.",
            )
            with self._lock:
                self.last_deliberation = decision
            self._persist_deliberation(decision)
            return decision

        # ── APPROVED ──────────────────────────────────────────────────
        # Determine urgency from agent confidence:
        # High combined confidence → MARKET; low → LIMIT (better fill)
        avg_conf = sum(v.confidence for v in panel_votes) / len(panel_votes) if panel_votes else 0.5
        urgency = "HIGH" if avg_conf >= 0.70 and agree_count == total_panel else "LOW"

        decision = TradeDecision(
            approved=True,
            signal=raw_signal,
            approved_qty=approved_qty,
            order_urgency=urgency,
            quorum_score=round(weighted_score, 3),
            votes=[v.to_dict() for v in votes],
            veto_agents=[],
            reasoning=(
                f"APPROVED: {agree_count}/{total_panel} agents agree, "
                f"score={weighted_score:.3f}, qty={approved_qty}, urgency={urgency}."
            ),
        )

        with self._lock:
            self.last_deliberation = decision

        self._logger.info(
            f"[{self.bot_id}] DELIBERATION APPROVED — {decision.reasoning}",
            extra={
                "event": "deliberation_approved",
                "bot_id": self.bot_id,
                "symbol": self.symbol,
                "signal": raw_signal,
                "approved_qty": approved_qty,
                "order_urgency": urgency,
                "quorum_score": round(weighted_score, 3),
                "agree_count": agree_count,
                "total_panel": total_panel,
                "avg_confidence": round(avg_conf, 3),
            },
        )
        self._persist_deliberation(decision)
        return decision

    def get_last_deliberation(self) -> Optional[dict]:
        """Return the last deliberation result as a dict (for API endpoints)."""
        with self._lock:
            return self.last_deliberation.to_dict() if self.last_deliberation else None

    def _persist_deliberation(self, decision: "TradeDecision") -> None:
        """
        Persist a TradeDecision to PostgreSQL (Phase 3 §5.3).

        Writes to the `strategy_contexts` table via `save_strategy_context`.
        Phase 4 §7.3 — prefers the bot's own event loop over the fleet-level
        `_main_event_loop` to isolate per-bot DB contention.
        Fire-and-forget — failures do NOT block deliberation.
        """
        try:
            import postgres_store
            loop = self._bot_loop or _main_event_loop
            if not (loop and loop.is_running()):
                return
            store = postgres_store.get_store() if postgres_store.is_initialized() else None
            if store is None:
                return
            payload = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision)
            payload["_kind"] = "deliberation"
            asyncio.run_coroutine_threadsafe(
                store.save_strategy_context(self.bot_id, payload), loop
            )
        except Exception as e:
            self._logger.debug(f"Deliberation persistence skipped: {e}")

    def get_agent_status(self) -> dict:
        """
        Return live status of all agents: last run time, last vote, confidence.
        Used by /fleet/bot/{bot_id}/agents/status API endpoint.
        """
        with self._lock:
            signals = dict(self.latest_signals)
        status = {}
        for agent_name in self.enabled_agents:
            sig = signals.get(agent_name)
            status[agent_name] = {
                "last_run_at": self.last_run_at,
                "last_sentiment": round(sig.sentiment, 3) if sig else None,
                "last_confidence": round(sig.confidence, 3) if sig else None,
                "last_reasoning": sig.reasoning[:120] if sig else None,
                "cache_age_seconds": round(time.time() - self._vote_timestamps.get(agent_name, 0))
                    if agent_name in self._vote_timestamps else None,
            }
        return status

    def _run_loop(self):
        """Background loop — runs agents every interval_minutes."""
        self._logger.info("Sub-agent loop starting")
        # Run immediately on start
        self._run_agents()
        while not self._stop_event.is_set():
            self._stop_event.wait(self.interval_minutes * 60)
            if not self._stop_event.is_set():
                self._run_agents()

    def _run_agents(self) -> dict[str, AgentSignal]:
        """Run all enabled agents in parallel and store results."""
        if not self.enabled_agents:
            return {}

        futures: dict[Future, str] = {}
        for agent_name in self.enabled_agents:
            agent = build_agent(
                agent_name=agent_name,
                bot_id=self.bot_id,
                symbol=self.symbol,
                openclaw_client=self._openclaw_client,
                openclaw_model=self._openclaw_model,
                ollama_base_url=self._ollama_base_url,
                ollama_model=self._ollama_model,
                market_trends=self.market_trends,
            )
            if agent:
                future = self._executor.submit(agent.run)
                futures[future] = agent_name

        results: dict[str, AgentSignal] = {}
        for future, agent_name in futures.items():
            try:
                signal = future.result(timeout=180)
                results[agent_name] = signal
                self._logger.info(
                    f"[{agent_name}] sentiment={signal.sentiment:+.2f} "
                    f"confidence={signal.confidence:.2f}"
                )
            except Exception as e:
                self._logger.error(
                    f"[{agent_name}] failed: {type(e).__name__}: {e}",
                    exc_info=True,
                )
                results[agent_name] = AgentSignal.neutral(agent_name, f"Error: {type(e).__name__}: {e}")

        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.latest_signals.update(results)
            self.last_run_at = now
            self.total_runs += 1

        return results
        return results
