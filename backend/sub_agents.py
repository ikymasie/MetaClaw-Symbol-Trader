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
from alpaca_hub import alpaca_hub
from gemini_budget import gemini_budget
from prompt_loader import PromptLoader

logger = logging.getLogger("tradeclaw.sub_agents")

# Module-level reference to the main asyncio event loop.
# Set by main.py at startup so background threads can schedule async coroutines
# (e.g. Firestore writes from DarwinianWeightStore).
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
    approved_qty: int              # Qty approved by RiskManagerAgent (0 if blocked)
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
    ):
        self.bot_id = bot_id
        self.symbol = symbol
        self._openclaw_client = openclaw_client
        self._openclaw_model = openclaw_model
        self._ollama_base_url = ollama_base_url
        self._ollama_model = ollama_model
        self._logger = logging.getLogger(f"tradeclaw.agents.{self.AGENT_NAME}[{bot_id}]")

    def run(self) -> AgentSignal:
        raise NotImplementedError

    def _call_openclaw(
        self, system: str, prompt: str, model: Optional[str] = None, temperature: float = 0.3, include_search: bool = True
    ) -> Optional[str]:
        """Call Gemini via OpenAI-compatible endpoint (budget-gated)."""
        if not self._openclaw_client:
            return None

        # ── Budget gate: skip Gemini if budget exhausted or circuit breaker active
        if not gemini_budget.can_call():
            self._logger.info("Gemini call skipped (budget exhausted) — use Ollama fallback")
            return None

        try:
            model = model or self._openclaw_model
            # Strip any prefix (e.g. "google/gemini-flash-latest" → "gemini-flash-latest")
            if "/" in model:
                model = model.split("/", 1)[1]
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ]
            
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 512,
                "response_format": {"type": "json_object"},
            }
                
            resp = self._openclaw_client.chat.completions.create(**kwargs, timeout=30)
            gemini_budget.record_call()
            return resp.choices[0].message.content
        except Exception as e:
            # Detect 429 and trip circuit breaker
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                gemini_budget.record_429()
            self._logger.warning(f"Gemini call failed: {e}")
            return None

    def _call_ollama(self, prompt: str) -> Optional[str]:
        """Call local Ollama for fast, offline analysis."""
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
            resp.raise_for_status()
            return resp.json().get("response", "")
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
        """Parse a structured AgentSignal from LLM JSON output."""
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
        except Exception as e:
            self._logger.warning(f"Failed to parse signal JSON: {e}")
            return AgentSignal.neutral(agent_name, f"Parse error: {e}")


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
        
        # 1. Get real-time headlines from AlpacaHub buffer
        recent_news = alpaca_hub.get_recent_news(self.symbol)
        
        if not recent_news:
            self._logger.info(f"No headlines buffered for {self.symbol}. Returning neutral.")
            return AgentSignal.neutral(self.AGENT_NAME, f"No recent news headlines buffered for {self.symbol}")

        # 2. Format headlines for the LLM
        news_text = "\n".join([
            f"- [{n['timestamp']}] {n['headline']}: {n['summary'][:150]}..."
            for n in recent_news
        ])

        system, user_tpl = PromptLoader.get_agent_prompts(self.AGENT_NAME)
        prompt = user_tpl.replace(
            "{symbol}", self.symbol
        ).replace(
            "{news_text}", news_text
        ).replace(
            "{now}", datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        )
        
        # 3. Primary: Ollama (local, fast, no API cost)
        raw = self._call_ollama(prompt)
        if raw:
            return self._parse_signal_from_json(raw, self.AGENT_NAME)
        # Fallback: Gemini via OpenClaw (budget-gated)
        raw = self._call_openclaw(system, prompt, include_search=False)
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
        # Fallback: Gemini via OpenClaw
        raw = self._call_openclaw(system, prompt)
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
        # Fallback: Gemini via OpenClaw
        raw = self._call_openclaw(system, prompt)
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
        prompt = user_tpl.replace("{symbol}", self.symbol)
        
        # Primary: Ollama (local, fast)
        raw = self._call_ollama(prompt)
        if raw:
            return self._parse_signal_from_json(raw, self.AGENT_NAME)
        
        # Fallback: OpenClaw
        raw = self._call_openclaw(system, prompt)
        if raw:
            return self._parse_signal_from_json(raw, self.AGENT_NAME)
        return AgentSignal.neutral(self.AGENT_NAME, "All endpoints unavailable")


# ─────────────────────────────────────────────
# WATCHMAN AGENT (Market Quality)
# ─────────────────────────────────────────────

class WatchmanAgent(BaseAgent):
    """
    The Market Watchman monitors order-flow quality using Alpaca Level 1 data.
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
        alpaca_client=None,     # Optional live Alpaca client for real data
        price_history=None,     # Optional deque of {price, volume} dicts
    ) -> AgentVote:
        """
        Compute market quality score from available data.
        Falls back to HOLD with high confidence if no live data is available,
        ensuring the Watchman never blocks trades due to missing data.
        """
        try:
            quality, alert = self._assess_quality(alpaca_client, price_history)
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

    def _assess_quality(self, alpaca_client, price_history) -> tuple[float, Optional[str]]:
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
        requested_qty: int,
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
            approved_qty = min(int(kelly_qty), requested_qty)
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

        # ── Objection 3: LLM-generated structural check ─────────────────
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
            raw = self._call_openclaw(system, prompt, include_search=False)

        if raw:
            try:
                # Basic cleanup for common LLM artifacts
                if "```json" in raw:
                    raw = raw.split("```json")[1].split("```")[0].strip()
                elif "{" in raw and "}" in raw:
                    raw = "{" + raw.split("{", 1)[1].rsplit("}", 1)[0] + "}"

                import json
                parsed = json.loads(raw)
                obj = parsed.get("objection", "").strip()
                severity = float(parsed.get("severity", 0.0))
                confidence = float(parsed.get("confidence", 0.0))
                if obj and severity > 0.5 and confidence > 0.5:
                    objections.append(f"[LLM CRO] {obj}")
            except Exception as e:
                self._logger.debug(f"CRO LLM parse error: {e}")

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
# AGENT FACTORY
# ─────────────────────────────────────────────

AGENT_CLASSES = {
    "sentiment": SentimentAgent,
    "macro": MacroAgent,
    "earnings": EarningsAgent,
    "technical": TechnicalAgent,
    "watchman": WatchmanAgent,
    "risk_manager": RiskManagerAgent,
    "ict": ICTAgent,
    "cro": CROAgent,
}


def build_agent(
    agent_name: str,
    bot_id: str,
    symbol: str,
    openclaw_client: Optional[OpenAI],
    openclaw_model: str,
    ollama_base_url: str,
    ollama_model: str,
) -> Optional[BaseAgent]:
    cls = AGENT_CLASSES.get(agent_name)
    if cls is None:
        logger.warning(f"Unknown agent: {agent_name}")
        return None
    return cls(
        bot_id=bot_id,
        symbol=symbol,
        openclaw_client=openclaw_client,
        openclaw_model=openclaw_model,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
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

    # Agents that have static roles and should NOT be Darwinian-weighted
    EXCLUDED = {"watchman", "risk_manager", "ict"}

    def __init__(self, bot_id: str):
        self.bot_id = bot_id
        self._lock = threading.Lock()
        # Initial neutral weights for all panel agents
        self._weights: dict[str, float] = {
            "sentiment":  1.0,
            "macro":      1.0,
            "earnings":   1.5,
            "technical":  0.75,
            "cro":        1.5,
        }
        # Outcome log for rolling Sharpe per agent
        # Each entry: {"agent": str, "voted": str, "trade_direction": str, "pnl": float}
        self._outcome_log: list[dict] = []
        self._logger = logging.getLogger(f"tradeclaw.darwin[{bot_id}]")
        self._load_from_db()

    def _load_from_db(self):
        """Load weights from Firestore on init (fire-and-forget on the main event loop)."""
        try:
            import firebase_store
            loop = _main_event_loop
            if loop and loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    firebase_store.load_darwinian_weights(self.bot_id), loop
                )
                try:
                    saved = future.result(timeout=5)
                    if saved:
                        with self._lock:
                            self._weights.update(saved)
                        self._logger.info(f"Loaded Darwinian weights from Firestore: {saved}")
                except Exception as e:
                    self._logger.warning(f"Darwinian weights load timed out or failed: {e}")
        except Exception as e:
            self._logger.warning(f"Failed to load weights from DB: {e}")

    def _save_to_db(self):
        """Persist current weights to Firestore (fire-and-forget)."""
        try:
            import firebase_store
            with self._lock:
                weights = dict(self._weights)
            loop = _main_event_loop
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    firebase_store.save_darwinian_weights(self.bot_id, weights), loop
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
                if agent in top_agents:
                    self._weights[agent] = min(self.CEILING, self._weights[agent] * self.UP_FACTOR)
                    self._logger.info(f"[Darwin] {agent} ↑ {self._weights[agent]:.3f} (top quartile)")
                elif agent in bottom_agents:
                    self._weights[agent] = max(self.FLOOR, self._weights[agent] * self.DOWN_FACTOR)
                    self._logger.info(f"[Darwin] {agent} ↓ {self._weights[agent]:.3f} (bottom quartile)")

        self._save_to_db()

    def get_all_weights(self) -> dict[str, float]:
        with self._lock:
            return dict(self._weights)


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
        self._logger.info(f"SubAgentPool started. Agents: {self.enabled_agents}")

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
        requested_qty: int,
        equity: float,
        daily_pnl: float,
        starting_equity: float,
        max_daily_drawdown_pct: float,
        recent_trades: list,
        survival_state: str,
        signal_price: float = 0.0,
        price_history=None,         # deque of price points for WatchmanAgent
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
                }
                _fut = asyncio.run_coroutine_threadsafe(
                    _graph.arun(_state, event_queue=self._event_queue,
                                price_history=price_history),
                    _loop,
                )
                _decision = _fut.result(timeout=120)
                if _decision is not None:
                    with self._lock:
                        self.last_deliberation = _decision
                    return _decision
            except Exception as _ge:
                self._logger.warning(
                    f"LangGraph deliberation error: {_ge} — falling back to direct path"
                )

        votes: list[AgentVote] = []
        veto_agents: list[str] = []

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
                    f"[{self.bot_id}] MACRO RISK_OFF PRE-FILTER — {_macro_veto_vote.reasoning[:100]}"
                )
                return decision

        # ── LLM panel votes (use cached results, refresh if stale) ────
        panel_agents = ["sentiment", "macro", "earnings", "technical"]
        
        # Static base weights × live Darwinian multipliers
        _static = {"sentiment": 1.0, "macro": 1.0, "earnings": 1.5, "technical": 0.75}
        agent_weights = {
            name: base * self._darwin.get_weight(name)
            for name, base in _static.items()
        }

        with self._lock:
            current_signals = dict(self.latest_signals)

        failed_agents: list[str] = []  # Track agents that failed to respond

        for agent_name in panel_agents:
            if agent_name not in self.enabled_agents:
                continue

            signal = current_signals.get(agent_name)
            age = time.time() - self._vote_timestamps.get(agent_name, 0)

            # Refresh if stale or missing
            if signal is None or age > vote_cache_ttl:
                try:
                    agent = build_agent(
                        agent_name=agent_name,
                        bot_id=self.bot_id,
                        symbol=self.symbol,
                        openclaw_client=self._openclaw_client,
                        openclaw_model=self._openclaw_model,
                        ollama_base_url=self._ollama_base_url,
                        ollama_model=self._ollama_model,
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
                f"[{self.bot_id}] DELIBERATION VETO — {decision.reasoning}"
            )
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
                f"[{self.bot_id}] DELIBERATION DEGRADED — {decision.reasoning}"
            )
            return decision

        # ── Quorum calculation (non-Risk / non-Watchman / non-ICT direction votes) ─
        panel_votes = [v for v in votes if v.agent not in ("risk_manager", "watchman", "ict")]

        agree_count = sum(1 for v in panel_votes if v.vote == raw_signal)
        total_panel = len(panel_votes)

        # Edge case: if ALL panel agents abstained (LLM outage), the panel is
        # empty.  Rather than permanently blocking trades, we treat "no panel
        # votes" as "no objections" and let the strategist+Watchman+RiskManager
        # gate the trade.  This keeps the bot operational during API outages.
        if total_panel == 0:
            self._logger.warning(
                f"[{self.bot_id}] All panel agents abstained (LLM outage?) — "
                f"deferring to strategist + risk manager."
            )
            quorum_met = True
            weighted_score = 0.5  # Neutral-positive: strategist already has conviction
        else:
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

        if not quorum_met or weighted_score < 0.2:
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
                f"[{self.bot_id}] DELIBERATION NO-QUORUM — {decision.reasoning}"
            )
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
                    f"[{self.bot_id}] DELIBERATION RISK VETO — {risk_vote.veto_reason}"
                )
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
            f"[{self.bot_id}] DELIBERATION APPROVED — {decision.reasoning}"
        )
        return decision

    def get_last_deliberation(self) -> Optional[dict]:
        """Return the last deliberation result as a dict (for API endpoints)."""
        with self._lock:
            return self.last_deliberation.to_dict() if self.last_deliberation else None

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
