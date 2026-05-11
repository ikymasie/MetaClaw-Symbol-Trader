import sys
import os
import logging
import asyncio
import re
import threading
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Try to import TradingAgents components
try:
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.agents.schemas import (
        ResearchPlan,
        PortfolioDecision,
        TraderProposal,
        PortfolioRating,
        TraderAction,
    )
except ImportError as e:
    logging.error(f"Failed to import TradingAgents: {e}")
    # Define placeholder types if imports fail for linting
    class ResearchPlan: pass
    class PortfolioDecision: pass
    class TraderProposal: pass
    class PortfolioRating: pass
    class TraderAction: pass

from symbol_mapper import symbol_mapper  # Phase 1 single source of truth
from sub_agents import AgentSignal
from config_manager import config_manager

logger = logging.getLogger("tradeclaw.research_bridge")

class ResearchBridge:
    """
    Bridge between TradingAgents research framework and TradeClaw execution engine.
    Translates long-form multi-agent research into structured AgentSignals.
    """
    
    def __init__(self, config_override: Optional[Dict[str, Any]] = None):
        self._config_override = config_override
        self._graph = None
        self._lock = threading.Lock()
        
    @property
    def graph(self):
        """Lazy-loaded TradingAgentsGraph instance."""
        if self._graph is None:
            with self._lock:
                if self._graph is None:
                    config = self._prepare_ta_config(self._config_override)
                    try:
                        self._graph = TradingAgentsGraph(config=config)
                    except Exception as e:
                        logger.error(f"Failed to initialize TradingAgentsGraph: {e}")
                        return None
        return self._graph

    def _prepare_ta_config(self, override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Prepare configuration for TradingAgentsGraph using ConfigManager."""
        # Use unmasked API keys from config_manager
        gemini_key = config_manager.get_api_key("gemini_api_key")
        
        # Get model config from config_manager with env fallback
        ai_config = config_manager.get_ai_config()
        fallback_model = ai_config.get("gemini_model") or "gemini-3.1-flash-lite"
        deep_think_model = (
            ai_config.get("deep_think_model")
            or os.getenv("DEEP_THINK_MODEL")
            or fallback_model
        )
        quick_think_model = (
            ai_config.get("quick_think_model")
            or os.getenv("QUICK_THINK_MODEL")
            or fallback_model
        )
        
        # Get alpaca key
        alpaca_key = config_manager.get_api_key("alpaca_news_api_key")
        
        ta_config = {
            "llm_provider": "google",
            "deep_think_llm": deep_think_model,
            "quick_think_llm": quick_think_model,
            "google_api_key": gemini_key,
            "alpaca_api_key": alpaca_key,
            # Data storage within project data dir
            "data_cache_dir": str(PROJECT_ROOT / "data" / "research_cache"),
            "results_dir": str(PROJECT_ROOT / "data" / "research_results"),
            "checkpoint_enabled": config_manager.get("RESEARCH_CHECKPOINT_ENABLED", True),
            "max_debate_rounds": config_manager.get("RESEARCH_DEBATE_ROUNDS", 2),
            "max_risk_discuss_rounds": config_manager.get("RESEARCH_RISK_ROUNDS", 1),
        }
        
        if override:
            ta_config.update(override)
            
        return ta_config

    # Canonical rating → sentiment mapping (PortfolioRating enum values + TraderAction).
    # PortfolioRating: Buy/Overweight/Hold/Underweight/Sell
    # TraderAction:    Buy/Hold/Sell
    _RATING_MAP: Dict[str, float] = {
        "Buy": 0.8,
        "Overweight": 0.4,
        "Hold": 0.0,
        "Underweight": -0.4,
        "Sell": -0.8,
    }

    @classmethod
    def _coerce_rating(cls, value: Any) -> Optional[str]:
        """Extract a canonical rating string from an enum, schema, or raw string."""
        if value is None:
            return None
        # Pydantic enum or any object with a .value attr
        v = getattr(value, "value", value)
        if not isinstance(v, str):
            return None
        v_clean = v.strip().capitalize()
        return v_clean if v_clean in cls._RATING_MAP else None

    def translate(self, plan: Any) -> AgentSignal:
        """
        Translate a TradingAgents pipeline output → backend AgentSignal.

        Accepted inputs (in preferred order):
          1. Typed Pydantic schemas: ResearchPlan, PortfolioDecision, TraderProposal
          2. `(final_state, processed_signal)` tuple from `TradingAgentsGraph.propagate(...)`
          3. dict with `recommendation` / `rating` / `action` keys
          4. Rendered markdown string (last-resort regex parse)
        """

        rating: Optional[str] = None
        rationale = "No research data available"

        # ── (2) Tuple from propagate() — try processed_signal first, then unwrap state
        if isinstance(plan, tuple) and len(plan) == 2:
            final_state, processed_signal = plan
            coerced = self._coerce_rating(processed_signal)
            if coerced:
                rating = coerced

            # Prefer the most adversarially-reviewed artifact for rationale
            if isinstance(final_state, dict):
                plan = (
                    final_state.get("final_trade_decision")
                    or final_state.get("investment_plan")
                    or final_state.get("trader_investment_plan")
                )

        # ── (1) Typed Pydantic schemas — preferred
        if isinstance(plan, ResearchPlan):
            rating = self._coerce_rating(plan.recommendation) or rating
            rationale = plan.rationale or rationale
        elif isinstance(plan, PortfolioDecision):
            rating = self._coerce_rating(plan.rating) or rating
            rationale = plan.investment_thesis or plan.executive_summary or rationale
        elif isinstance(plan, TraderProposal):
            rating = self._coerce_rating(plan.action) or rating
            rationale = plan.reasoning or rationale

        # ── (3) dict
        elif isinstance(plan, dict):
            rating = (
                self._coerce_rating(plan.get("recommendation"))
                or self._coerce_rating(plan.get("rating"))
                or self._coerce_rating(plan.get("action"))
                or rating
            )
            rationale = (
                plan.get("rationale")
                or plan.get("investment_thesis")
                or plan.get("reasoning")
                or rationale
            )

        # ── (4) Markdown string fallback
        elif isinstance(plan, str):
            if rating is None:
                rating_match = re.search(
                    r"\*\*(?:Recommendation|Rating|Action)\*\*:?\s*(\w+)",
                    plan, re.IGNORECASE,
                )
                if rating_match:
                    rating = self._coerce_rating(rating_match.group(1))

            rationale_match = re.search(
                r"\*\*(?:Rationale|Investment Thesis|Executive Summary|Reasoning)\*\*:?\s*(.*?)(?:\n\n|\n\*\*|$)",
                plan, re.DOTALL | re.IGNORECASE,
            )
            if rationale_match:
                rationale = rationale_match.group(1).strip()
            else:
                rationale = plan[:500]

        # Final default — Hold/neutral
        if rating is None:
            rating = "Hold"

        sentiment = self._RATING_MAP.get(rating, 0.0)

        return AgentSignal(
            agent="research_framework",
            sentiment=sentiment,
            confidence=0.85,  # High: full multi-analyst debate pipeline
            reasoning=(rationale or "")[:500],
        )

    async def run_research(self, symbol: str, force: bool = False) -> AgentSignal:
        """
        Runs a research cycle for a symbol and returns the signal.
        Checks PostgreSQL cache first unless force=True.
        """
        from postgres_store import get_store
        
        # 1. Check Cache
        if not force:
            try:
                store = get_store()
                cached = await store.get_latest_research_report(symbol)
                if cached:
                    report_data, updated_at = cached
                    age_seconds = (datetime.now(updated_at.tzinfo) - updated_at).total_seconds()
                    ttl = config_manager.get("RESEARCH_CACHE_TTL", 14400) # 4 hours default
                    
                    if age_seconds < ttl:
                        logger.info(f"Using cached research report for {symbol} (age: {age_seconds/3600:.1f}h)")
                        # cached report_data contains the AgentSignal fields
                        return AgentSignal(
                            agent=report_data.get("agent", "research_framework"),
                            sentiment=report_data.get("sentiment", 0.0),
                            confidence=report_data.get("confidence", 0.0),
                            reasoning=report_data.get("reasoning", "")
                        )
            except Exception as e:
                logger.warning(f"Cache lookup failed for {symbol}: {e}")

        # 2. Run Graph
        g = self.graph
        if not g:
            return AgentSignal.neutral("research_framework", reason="Research graph not initialized")

        research_symbol = symbol_mapper.to_research(symbol)
        from datetime import timezone
        trade_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        logger.info(f"Triggering research cycle for {symbol} (as {research_symbol})")
        
        try:
            # TradingAgentsGraph.propagate is synchronous, run in thread to keep loop free
            result = await asyncio.to_thread(
                g.propagate, research_symbol, trade_date
            )
            
            if not result or not isinstance(result, tuple):
                raise ValueError(f"Unexpected graph result: {result}")
                
            signal = self.translate(result)
            
            # 3. Save to Cache
            try:
                store = get_store()
                await store.save_research_report(symbol, {
                    "agent": signal.agent,
                    "sentiment": signal.sentiment,
                    "confidence": signal.confidence,
                    "reasoning": signal.reasoning,
                    "raw_result": str(result[0]) if result else None # Save some context
                })
            except Exception as e:
                logger.warning(f"Failed to cache research report for {symbol}: {e}")

            return signal
            
        except Exception as e:
            logger.error(f"Research cycle failed for {symbol}: {e}", exc_info=True)
            return AgentSignal.neutral("research_framework", reason=f"Research failed: {str(e)}")

# Singleton instance
research_bridge = ResearchBridge()
