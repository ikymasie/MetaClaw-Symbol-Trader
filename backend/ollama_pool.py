"""
TradeClaw — Ollama Model Pool (Phase 4 §6.4)
===============================================
Per-agent model selection so different complexity tiers use appropriately
sized models instead of all routing through the same default `gemma4:e4b`.

Recommendations from the spec:

  Agent            | Recommended Ollama Model | Reason
  ─────────────────┼──────────────────────────┼─────────────────────
  WatchmanAgent    | gemma4:e4b               | Simple price action
  MacroAgent       | gemma4:e12b              | Complex macro reasoning
  CROAgent         | gemma4:e12b              | Adversarial analysis
  SentimentAgent   | gemma4:e4b               | Text classification
  TechnicalAgent   | gemma4:e4b               | Chart pattern reasoning
  EarningsAgent    | gemma4:e4b               | Calendar proximity

Usage — the pool is a simple dict; it is consulted by `build_agent()` in
sub_agents.py which overrides the fleet-level `ollama_model` default per agent.

To customise, operators can set the env variable `OLLAMA_MODEL_<AGENT>` e.g.
`OLLAMA_MODEL_MACRO=qwen3:14b`.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger("tradeclaw.ollama_pool")

# Agent → recommended Ollama model (fallback to env var if set, else default)
_OLLAMA_MODEL_POOL = {
    "watchman":   os.getenv("OLLAMA_MODEL_WATCHMAN",   "gemma4:e4b"),
    "sentiment":  os.getenv("OLLAMA_MODEL_SENTIMENT",  "gemma4:e4b"),
    "earnings":   os.getenv("OLLAMA_MODEL_EARNINGS",   "gemma4:e4b"),
    "technical":  os.getenv("OLLAMA_MODEL_TECHNICAL",  "gemma4:e4b"),
    "correlation": os.getenv("OLLAMA_MODEL_CORRELATION", "gemma4:e4b"),
    "orderflow":  os.getenv("OLLAMA_MODEL_ORDERFLOW",  "gemma4:e4b"),
    "macro":      os.getenv("OLLAMA_MODEL_MACRO",       "gemma4:e12b"),
    "cro":        os.getenv("OLLAMA_MODEL_CRO",         "gemma4:e12b"),
    "calendar":   os.getenv("OLLAMA_MODEL_CALENDAR",    "gemma4:e4b"),
    "ict":        os.getenv("OLLAMA_MODEL_ICT",         "gemma4:e4b"),
    "trend":      os.getenv("OLLAMA_MODEL_TREND",       "gemma4:e4b"),
    "regime":     os.getenv("OLLAMA_MODEL_REGIME",      "gemma4:e4b"),
    "risk_manager": os.getenv("OLLAMA_MODEL_RISK",      "gemma4:e4b"),
    "research_framework": os.getenv("OLLAMA_MODEL_RESEARCH", "gemma4:e4b"),
}


def get_ollama_model(agent_name: str, fleet_default: Optional[str] = None) -> str:
    """
    Resolve the best Ollama model for an agent.

    Priority:
      1. OLLAMA_MODEL_<AGENT> environment variable
      2. Pool default (spec-recommended per §6.4)
      3. Fleet-level `ollama_model` config field (passed from fleet/sys config)
      4. Hardcoded `gemma4:e4b` fallback
    """
    model = _OLLAMA_MODEL_POOL.get(agent_name)
    if model:
        return model
    return fleet_default or "gemma4:e4b"
