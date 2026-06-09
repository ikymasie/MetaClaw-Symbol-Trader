"""
TradeClaw — Per-Bot AI Brain Scheduler
========================================
Refactored from the singleton AIBrainScheduler into an instantiable class.
Each bot has its own AI Brain that:
  - Aggregates sub-agent signals before each evolution cycle
  - Persists decisions to Firebase (Firestore)
  - Stores strategy contexts for RAG memory retrieval
  - Uses the organism prompt system from its own VitalSigns
"""

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

import httpx
from openai import OpenAI

from bot_config import BotConfig
from bot_vital_signs import BotVitalSigns, build_organism_system_prompt
from gemini_budget import gemini_budget

logger = logging.getLogger("tradeclaw.bot_ai_brain")


# ─────────────────────────────────────────────
# PARAM GUARDRAILS
# ─────────────────────────────────────────────

PARAM_BOUNDS: dict[str, tuple] = {
    "bb_period": (8, 100),
    "bb_std_dev": (1.0, 3.5),
    "stop_loss_pct": (0.25, 5.0),
    "qty": (1, 50),
    "fib_lookback_bars": (20, 200),
    "fib_bounce_threshold_pct": (0.05, 1.0),
}


class ParamGuardrail:
    @staticmethod
    def validate(params: dict) -> tuple[dict, list[str]]:
        valid = {}
        warnings = []
        required = {"bb_period", "bb_std_dev", "stop_loss_pct", "qty"}
        optional_fib = {"fib_lookback_bars", "fib_bounce_threshold_pct"}

        for key in required:
            if key not in params:
                raise ValueError(f"AI response missing required key: {key}")

        all_keys = required | (optional_fib & params.keys())
        for key in all_keys:
            if key not in params:
                continue
            raw = params[key]
            lo, hi = PARAM_BOUNDS[key]
            val = int(round(raw)) if key in ("bb_period", "fib_lookback_bars", "qty") else float(raw)
            clamped = max(lo, min(hi, val))
            if clamped != val:
                warnings.append(f"{key}: suggested {val}, clamped to {clamped} (bounds {lo}–{hi})")
            valid[key] = clamped
        return valid, warnings


# ─────────────────────────────────────────────
# BOT AI BRAIN SCHEDULER
# ─────────────────────────────────────────────

class BotAIBrainScheduler:
    """
    Per-bot AI Brain. Runs an evolution cycle triggered by:
      - Loss streak        (immediate)
      - Trade count        (N new trades)
      - Schedule           (every N minutes)
      - Manual trigger     (from portal)

    Before each cycle, aggregates sub-agent signals and injects them
    into the AI prompt as additional market context.
    Saves decisions to Firestore and strategy contexts for RAG.
    """

    def __init__(
        self,
        bot_id: str,
        bot_config: BotConfig,
        engine,                          # BotEngine instance
        vital_signs: BotVitalSigns,
        sub_agent_pool=None,             # SubAgentPool instance (optional)
        openclaw_client: Optional[OpenAI] = None,
        openclaw_model: str = "google/gemini-flash-latest",
        ollama_base_url: str = "http://localhost:11434",
        ollama_model: str = "gemma4:e4b",
        store=None,
        main_loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.bot_id = bot_id
        self.bot_config = bot_config
        self._engine = engine
        self._vital_signs = vital_signs
        self._sub_agent_pool = sub_agent_pool
        self._openclaw_client = openclaw_client
        self._openclaw_model = openclaw_model
        self._ollama_base_url = ollama_base_url
        self._ollama_model = ollama_model
        self._store = store
        self._main_loop = main_loop
        self._logger = logging.getLogger(f"tradeclaw.bot_ai_brain[{bot_id}]")

        # State
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.enabled = False
        self.last_run_at: Optional[str] = None
        self.last_trigger: Optional[str] = None
        self.last_decision: Optional[dict] = None
        self.total_cycles: int = 0
        self._last_trade_count: int = 0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self.enabled = True
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"ai-brain-{self.bot_id}",
        )
        self._thread.start()
        self._logger.info("AI Brain started")

    def stop(self):
        self.enabled = False
        self._stop_event.set()
        self._logger.info("AI Brain stopped")

    def trigger_manual(self):
        threading.Thread(
            target=self._run_cycle,
            args=("MANUAL",),
            daemon=True,
            name=f"ai-brain-manual-{self.bot_id}",
        ).start()

    def get_status(self) -> dict:
        with self._lock:
            return {
                "bot_id": self.bot_id,
                "enabled": self.enabled,
                "last_run_at": self.last_run_at,
                "last_trigger": self.last_trigger,
                "total_cycles": self.total_cycles,
                "last_decision": self.last_decision,
                "interval_minutes": self.bot_config.ai_interval_minutes,
            }

    def _run_loop(self):
        self._logger.info("AI Brain loop running")
        while not self._stop_event.is_set():
            try:
                self._check_triggers()
            except Exception as e:
                self._logger.error(f"AI Brain loop error: {e}", exc_info=True)
            self._stop_event.wait(30)

    def _check_triggers(self):
        cfg = self.bot_config
        trades = self._engine.get_recent_trades(200)
        closed = [t for t in trades if t.get("side") in ("SELL", "STOP_LOSS", "HALT")]
        total_closed = len(closed)

        # Loss streak trigger
        consecutive_losses = 0
        for t in reversed(closed):
            if t.get("pnl", 0) < 0:
                consecutive_losses += 1
            else:
                break
        if consecutive_losses >= cfg.ai_loss_streak_trigger:
            self._logger.warning(f"LOSS_STREAK trigger ({consecutive_losses})")
            self._run_cycle(f"LOSS_STREAK:{consecutive_losses}", trades)
            return

        # Trade count trigger
        new_trades = total_closed - self._last_trade_count
        if new_trades >= cfg.ai_min_trades_trigger and total_closed > 0:
            self._last_trade_count = total_closed
            self._run_cycle("TRADE_COUNT", trades)
            return

        # Schedule trigger
        interval_secs = cfg.ai_interval_minutes * 60
        if self.last_run_at:
            elapsed = (
                datetime.now(timezone.utc) - datetime.fromisoformat(self.last_run_at)
            ).total_seconds()
            if elapsed >= interval_secs:
                # Budget-aware: skip SCHEDULE triggers when Gemini budget is
                # exhausted.  LOSS_STREAK and MANUAL triggers are always honoured
                # (they use Ollama fallback).  This prevents burning budget on
                # routine cycles that can safely wait.
                if not gemini_budget.can_call():
                    self._logger.info(
                        "AI Brain SCHEDULE skipped — Gemini budget exhausted. "
                        "Waiting for budget reset or LOSS_STREAK trigger."
                    )
                    return
                self._run_cycle("SCHEDULE", trades)
        else:
            if total_closed >= max(5, cfg.ai_min_trades_trigger):
                self._run_cycle("SCHEDULE:initial", trades)

    def _run_cycle(self, trigger: str, trades: Optional[list] = None):
        """Execute one evolution cycle."""
        now_str = datetime.now(timezone.utc).isoformat()

        if trades is None:
            trades = self._engine.get_recent_trades(200)

        # Compute metrics
        from ai_brain import PerformanceAnalyser
        equity_history = self._engine.get_equity_history(50)
        metrics = PerformanceAnalyser(trades, equity_history).compute()

        if metrics["total_trades"] == 0 and "MANUAL" not in trigger:
            self._logger.info("No closed trades yet, skipping scheduled cycle")
            return
        if metrics["total_trades"] == 0:
            self._logger.info("Running baseline assessment (0 trades)")

        # Gather sub-agent sentiment
        agent_context = self._build_agent_context()

        # Get current params from engine
        current_params = self._engine.get_current_params()

        # Build RAG context from Firebase
        rag_context = self._get_rag_context()

        # Build Market Context (Multi-timeframe trends)
        market_context = self._get_market_context()

        # Build prompt
        prompt = self._build_prompt(metrics, current_params, trigger, agent_context, rag_context, market_context)
        system_prompt = self._get_system_prompt()

        # Call LLM
        result = self._call_llm(prompt, system_prompt)
        if not result.get("applied"):
            # Persist degraded decision so the dashboard shows why AI couldn't run
            degraded_decision = {
                "timestamp": now_str,
                "trigger": trigger,
                "trades_analysed": metrics["total_trades"],
                "win_rate_before": metrics["win_rate"],
                "daily_pnl_before": metrics["daily_pnl"],
                "params_before": json.dumps(current_params),
                "params_after": json.dumps({}),
                "reasoning": f"LLM unavailable: {result.get('error', 'unknown')}",
                "model_used": "none",
                "applied": False,
                "agent_context": agent_context,
            }
            self._logger.warning(f"AI cycle degraded: {result.get('error')}")
            if self._store and self._main_loop and self._main_loop.is_running():
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self._store.save_ai_decision(self.bot_id, degraded_decision),
                        self._main_loop,
                    )
                    future.result(timeout=10)
                    self._logger.info(f"Degraded AI decision saved to Postgres (trigger={trigger})")
                except Exception as e:
                    self._logger.error(f"Failed to save degraded decision: {e}")
            with self._lock:
                self.last_run_at = now_str
                self.last_trigger = trigger
                self.total_cycles += 1
                self.last_decision = {
                    "trigger": trigger,
                    "applied": False,
                    "error": result.get("error", "unknown"),
                    "timestamp": now_str,
                }
            return

        # Apply params to engine
        self._engine.update_params(result["new_params"])

        # Persist to Firestore
        decision = {
            "timestamp": now_str,
            "trigger": trigger,
            "trades_analysed": metrics["total_trades"],
            "win_rate_before": metrics["win_rate"],
            "daily_pnl_before": metrics["daily_pnl"],
            "params_before": json.dumps(current_params),
            "params_after": json.dumps(result.get("new_params", {})),
            "reasoning": result.get("reasoning", ""),
            "model_used": result.get("model_used", "unknown"),
            "applied": result.get("applied", False),
            "agent_context": agent_context,
            "market_context": market_context,
        }

        if self._store and self._main_loop and self._main_loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._store.save_ai_decision(self.bot_id, decision),
                    self._main_loop,
                )
                future.result(timeout=10)
                self._logger.info(f"AI decision saved to Postgres (trigger={trigger})")
            except Exception as e:
                self._logger.error(f"Failed to save AI decision to Postgres: {e}", exc_info=True)

            # Save strategy context for RAG
            try:
                rag_future = asyncio.run_coroutine_threadsafe(
                    self._store.save_strategy_context(
                        bot_id=self.bot_id,
                        context={
                            "metrics": metrics,
                            "params_before": current_params,
                            "params_after": result.get("new_params"),
                            "reasoning": result.get("reasoning"),
                            "trigger": trigger,
                        },
                        embedding_text=result.get("reasoning", ""),
                    ),
                    self._main_loop,
                )
                rag_future.result(timeout=10)
            except Exception as e:
                self._logger.warning(f"Failed to save RAG strategy context: {e}")
        elif self._store:
            self._logger.warning("Cannot save AI decision — main event loop not available or not running")

        with self._lock:
            self.last_run_at = now_str
            self.last_trigger = trigger
            self.total_cycles += 1
            self.last_decision = {
                "trigger": trigger,
                "timestamp": now_str,
                "metrics_summary": {
                    "total_trades": metrics["total_trades"],
                    "win_rate": metrics["win_rate"],
                    "total_pnl": metrics["total_pnl"],
                },
                "params_after": result.get("new_params"),
                "reasoning": result.get("reasoning"),
                "model_used": result.get("model_used"),
            }

        self._logger.info(f"Cycle complete. Trigger={trigger} Applied={result.get('applied')}")

    def _build_agent_context(self) -> dict:
        if not self._sub_agent_pool:
            return {}
        try:
            return self._sub_agent_pool.get_aggregate_sentiment()
        except Exception:
            return {}

    def _get_rag_context(self) -> list[dict]:
        """Retrieve recent strategy contexts from Postgres for RAG grounding."""
        if not self._store or not self._main_loop or not self._main_loop.is_running():
            return []
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._store.retrieve_recent_strategy_contexts(
                    bot_id=self.bot_id, limit=3
                ),
                self._main_loop,
            )
            return future.result(timeout=10)
        except Exception as e:
            self._logger.warning(f"RAG context fetch failed: {e}")
            return []

    def _get_market_context(self) -> dict:
        """Fetch multi-timeframe trend summaries from Postgres."""
        if not self._store or not self._main_loop or not self._main_loop.is_running():
            return {}
        
        symbol = self.bot_config.symbol
        timeframes = ["1m", "15m", "1h", "1d"]
        context = {}
        
        for tf in timeframes:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._store.get_trend_summary(symbol, tf),
                    self._main_loop,
                )
                summary = future.result(timeout=5)
                if summary:
                    context[tf] = summary
            except Exception as e:
                self._logger.warning(f"Failed to fetch {tf} trend for {symbol}: {e}")
        
        return context

    def _build_prompt(
        self,
        metrics: dict,
        current_params: dict,
        trigger: str,
        agent_context: dict,
        rag_context: list,
        market_context: dict,
    ) -> str:
        vs = self._vital_signs.get_status()
        survival_directive = ""
        if vs["survival_state"] in ("WOUNDED", "ORGAN_FAILURE", "DECEASED"):
            survival_directive = (
                f"\n⚠️ SURVIVAL ALERT: {vs['survival_state']} "
                f"(drawdown={vs['drawdown_pct']:.1f}%). "
                f"PRIORITISE capital preservation. Reduce qty and tighten stops."
            )
        elif vs["apex_tier"] >= 2:
            survival_directive = (
                f"\n🦾 APEX MODE: {vs['apex_state']} "
                f"(profit={vs['profit_pct']:.1f}%). Scale aggression."
            )

        # Agent sentiment block
        agent_block = ""
        if agent_context:
            score = agent_context.get("score", 0.0)
            confidence = agent_context.get("confidence", 0.0)
            breakdown = agent_context.get("breakdown", {})
            agent_block = f"""
MARKET INTELLIGENCE (sub-agent aggregate):
- Aggregate Sentiment: {score:+.2f} (confidence: {confidence:.0%})"""
            for agent, data in breakdown.items():
                agent_block += f"\n  · {agent}: {data['sentiment']:+.2f} — {data['reasoning']}"

        # RAG memory block
        rag_block = ""
        if rag_context:
            rag_block = "\nRECENT STRATEGY MEMORY (RAG):"
            for ctx in rag_context[-3:]:
                c = ctx.get("context", {})
                rag_block += (
                    f"\n  [{ctx.get('timestamp', '')[:10]}] "
                    f"Trigger={c.get('trigger','')} | "
                    f"WinRate={c.get('metrics',{}).get('win_rate',0)}% | "
                    f"Reasoning: {c.get('reasoning','')[:100]}"
                )

        # Market context block
        market_block = ""
        if market_context:
            market_block = "\nMARKET CONTEXT (Multi-Timeframe):"
            for tf in ["1d", "1h", "15m", "1m"]:
                if tf in market_context:
                    s = market_context[tf]
                    market_block += (
                        f"\n  · {tf.upper()}: {s.get('regime','?')} | "
                        f"Trend: {s.get('trend_direction','?')} | "
                        f"ADX: {s.get('adx',0):.1f} | RSI: {s.get('rsi',0):.1f}"
                    )

        return f"""ANALYSIS TRIGGER: {trigger}{survival_directive}
{market_block}
{agent_block}
{rag_block}

CURRENT VITAL STATE: {vs['survival_state']} | Apex: {vs['apex_state']}

CURRENT STRATEGY PARAMETERS:
- BB Period: {current_params.get('bb_period', '?')} (bounds: 8–100)
- BB Std Dev: {current_params.get('bb_std_dev', '?')} (bounds: 1.0–3.5)
- Stop Loss %: {current_params.get('stop_loss_pct', '?')} (bounds: 0.25–5.0)
- Position Qty: {current_params.get('qty', '?')} (bounds: 1–50)
- Fib Lookback: {current_params.get('fib_lookback_bars', 50)} (bounds: 20–200)
- Fib Bounce Threshold: {current_params.get('fib_bounce_threshold_pct', 0.20)} (bounds: 0.05–1.0)

PERFORMANCE METRICS (last {metrics['total_trades']} closed trades):
- Win Rate: {metrics['win_rate']}%
- Avg Win: ${metrics['avg_win']:+.2f} | Avg Loss: ${metrics['avg_loss']:+.2f}
- Profit Factor: {metrics['profit_factor']}
- Loss Streak: {metrics['current_loss_streak']}
- Total PnL: ${metrics['total_pnl']:+.2f}
- Sharpe: {metrics['sharpe_ratio']}

Respond ONLY with this JSON:
{{
  "bb_period": <int 8-100>,
  "bb_std_dev": <float 1.0-3.5>,
  "stop_loss_pct": <float 0.25-5.0>,
  "qty": <int 1-50>,
  "fib_lookback_bars": <int 20-200>,
  "fib_bounce_threshold_pct": <float 0.05-1.0>,
  "reasoning": "<2-3 sentences>"
}}"""

    def _get_system_prompt(self) -> str:
        vs = self._vital_signs.get_status()
        return build_organism_system_prompt(
            survival_state=vs["survival_state"],
            apex_state=vs["apex_state"],
            profit_pct=vs["profit_pct"],
            drawdown_pct=vs["drawdown_pct"],
        )

    def _call_llm(self, prompt: str, system_prompt: str) -> dict:
        """Call Gemini via OpenAI-compatible endpoint, falling back to local Ollama.

        Fallback chain:
          1. Gemini (primary) — cloud, fast, high quality (budget-gated)
          2. Ollama/Gemma 4B (fallback) — local, offline, no rate limits
        """
        budget = self._vital_signs.get_status()["intelligence_budget"]
        model = budget.get("model", self._openclaw_model)
        # Strip any OpenClaw-style prefix (e.g. "google/gemini-flash-latest" → "gemini-flash-latest")
        if "/" in model:
            model = model.split("/", 1)[1]
        temperature = budget.get("temperature", 0.3)

        # ── 1. Try Gemini (primary, budget-gated) ────────────────────
        if self._openclaw_client and gemini_budget.can_call():
            try:
                self._logger.info(f"Calling Gemini model={model} temp={temperature}")
                response = self._openclaw_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    max_tokens=512,
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content
                gemini_budget.record_call()
                self._logger.info(f"Gemini response received ({len(raw)} chars)")
                return self._parse_and_apply(raw, model)
            except Exception as e:
                # Detect 429 and trip circuit breaker
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    gemini_budget.record_429()
                self._logger.warning(f"Gemini call failed: {e} — falling back to Ollama")
        elif not self._openclaw_client:
            self._logger.warning("No Gemini client available — trying Ollama directly")
        else:
            self._logger.info("Gemini budget exhausted — using Ollama for AI brain cycle")

        # ── 2. Fallback: local Ollama ──────────────────────────────
        return self._call_ollama_direct(prompt, system_prompt, temperature)

    def _call_ollama_direct(
        self, prompt: str, system_prompt: str, temperature: float = 0.3
    ) -> dict:
        """Call local Ollama REST API as LLM fallback."""
        try:
            ollama_model = self._ollama_model
            self._logger.info(
                f"Calling Ollama fallback: {self._ollama_base_url} model={ollama_model}"
            )
            payload = {
                "model": ollama_model,
                "prompt": f"{system_prompt}\n\n{prompt}",
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": temperature,
                    "num_predict": 512,
                },
            }
            resp = httpx.post(
                f"{self._ollama_base_url}/api/generate",
                json=payload,
                timeout=90.0,  # Ollama on CPU can be slow
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            if not raw:
                return {"applied": False, "error": "Ollama returned empty response"}
            self._logger.info(
                f"Ollama response received ({len(raw)} chars) via {ollama_model}"
            )
            return self._parse_and_apply(raw, f"ollama/{ollama_model}")
        except Exception as e:
            self._logger.error(f"Ollama fallback also failed: {e}")
            return {"applied": False, "error": f"All LLM endpoints failed: {e}"}

    def _parse_and_apply(self, raw: str, model_used: str) -> dict:
        import re
        raw = raw.strip()
        parsed = None
        for attempt in [
            lambda: json.loads(raw),
            lambda: json.loads(re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL).group(1)),
            lambda: json.loads(re.search(r"\{.*\}", raw, re.DOTALL).group(0)),
        ]:
            try:
                parsed = attempt()
                break
            except Exception:
                continue

        if not parsed:
            return {"applied": False, "error": "JSON parse failed"}

        try:
            validated, warnings = ParamGuardrail.validate(parsed)
        except ValueError as e:
            return {"applied": False, "error": str(e)}

        return {
            "applied": True,
            "new_params": validated,
            "reasoning": parsed.get("reasoning", ""),
            "model_used": model_used,
            "warnings": warnings,
        }
