"""
TradeClaw AI Brain — Strategy Evolution Engine
============================================
Uses OpenClaw (OpenAI-compatible proxy) with google/gemini-flash-latest as the
primary model, falling back to ollama/gemma4:e4b for offline operation.

The AI Brain analyses historical trade performance and autonomously adjusts
Bollinger Band strategy parameters to maximise profit and minimise loss.

Now powered by the Apex Predator Behavioral System:
- Dynamic model selection based on profit tier (Hunting → Singularity)
- Organism system prompt injected on every LLM call
- Survival state awareness baked into every recommendation
"""

from __future__ import annotations
import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from openai import OpenAI

from config import config
from postgres_store import (
    get_recent_trades_for_analysis,
    _legacy_get_equity_history as get_equity_history,
    save_ai_decision,
)
from vital_signs import vital_signs

logger = logging.getLogger("tradeclaw.ai_brain")


# Module-level reference to the main uvicorn event loop.
# Captured when AIBrainScheduler.start() is called during app lifespan.
_captured_main_loop: asyncio.AbstractEventLoop | None = None


def _run_async(coro, timeout: float = 15):
    """Run an async coroutine from a synchronous (background) thread.

    Dispatches *coro* onto the captured main event loop via
    ``run_coroutine_threadsafe`` so that Firestore's gRPC channel
    (which is bound to that loop) is reused correctly.

    IMPORTANT: Never create a fallback event loop — Firestore's gRPC
    channels are bound to the main loop and will raise
    "attached to a different loop" if used from a fresh loop.
    """
    loop = _captured_main_loop

    if loop is None:
        logger.error("_run_async: main event loop not captured — cannot dispatch coroutine")
        # Close the unawaited coroutine to avoid ResourceWarning
        coro.close()
        return None

    if not loop.is_running():
        logger.error("_run_async: main event loop exists but is not running")
        coro.close()
        return None

    try:
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=timeout)
    except Exception as e:
        logger.error(f"_run_async: coroutine dispatch failed: {e}")
        return None


# ─────────────────────────────────────────────
# PARAM GUARDRAILS — hard bounds the AI cannot exceed
# ─────────────────────────────────────────────

PARAM_BOUNDS: dict[str, tuple] = {
    "bb_period": (8, 100),
    "bb_std_dev": (1.0, 3.5),
    "stop_loss_pct": (0.25, 5.0),
    "qty": (1, 50),
    # Fibonacci params
    "fib_lookback_bars": (20, 200),
    "fib_bounce_threshold_pct": (0.05, 1.0),
    # Regime / Momentum params
    "adx_trend_threshold": (15.0, 45.0),
    "ema_fast": (5, 20),
    "ema_mid": (15, 50),
    "ema_slow": (30, 100),
    # Kelly sizing
    "kelly_fraction": (0.05, 0.50),
    # VWAP Analyser — how many SDs from VWAP before flagging an entry zone
    # 2.0 = aggressive (more entries), 3.0 = strict (institutional-grade)
    "vwap_entry_sd": (1.5, 3.5),
}


class ParamGuardrail:
    """Validates and clamps AI-suggested parameters to safe bounds."""

    @staticmethod
    def validate(params: dict) -> tuple[dict, list[str]]:
        """
        Returns (valid_params, warnings). Clamps values to bounds.
        Raises ValueError if a required key is missing.
        """
        valid = {}
        warnings = []
        required = {"bb_period", "bb_std_dev", "stop_loss_pct", "qty"}
        optional_fib = {"fib_lookback_bars", "fib_bounce_threshold_pct"}
        optional_survival = {
            "adx_trend_threshold", "ema_fast", "ema_mid", "ema_slow",
            "kelly_fraction", "vwap_entry_sd",
        }

        for key in required:
            if key not in params:
                raise ValueError(f"AI response missing required key: {key}")

        all_keys = required | (optional_fib & params.keys()) | (optional_survival & params.keys())

        for key in all_keys:
            if key not in params:
                continue
            raw = params[key]
            lo, hi = PARAM_BOUNDS[key]

            if key in ("bb_period", "fib_lookback_bars", "qty", "ema_fast", "ema_mid", "ema_slow"):
                val = int(round(raw))
            else:
                val = float(raw)

            clamped = max(lo, min(hi, val))
            if clamped != val:
                warnings.append(
                    f"{key}: AI suggested {val}, clamped to {clamped} (bounds {lo}\u2013{hi})"
                )
            valid[key] = clamped

        return valid, warnings


# ─────────────────────────────────────────────
# PERFORMANCE ANALYSER
# ─────────────────────────────────────────────

class PerformanceAnalyser:
    """Computes performance metrics from recent trade history."""

    def __init__(self, trades: list[dict], equity_snapshots: list[dict]):
        self.trades = trades
        self.equity_snapshots = equity_snapshots

    def compute(self) -> dict:
        closed = [t for t in self.trades if t["side"] in ("SELL", "STOP_LOSS")]

        if not closed:
            return self._empty_metrics()

        pnls = [t["pnl"] for t in closed]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        total = len(pnls)
        win_count = len(wins)

        win_rate = (win_count / total * 100) if total else 0.0
        avg_win = (sum(wins) / len(wins)) if wins else 0.0
        avg_loss = (sum(losses) / len(losses)) if losses else 0.0
        total_pnl = sum(pnls)

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

        # Consecutive loss streak
        streak = 0
        max_streak = 0
        current_streak = 0
        for p in reversed(pnls):
            if p < 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
                if streak == 0:
                    streak = current_streak
            else:
                if streak == 0:
                    current_streak = 0
                else:
                    current_streak = 0

        # Daily PnL from equity snapshots
        daily_pnl = 0.0
        if self.equity_snapshots and len(self.equity_snapshots) >= 2:
            daily_pnl = (
                self.equity_snapshots[-1]["daily_pnl"]
                if "daily_pnl" in self.equity_snapshots[-1]
                else 0.0
            )

        # Sharpe-like ratio (simplified)
        if total > 1:
            import numpy as np
            pnl_arr = list(pnls)
            mean = sum(pnl_arr) / len(pnl_arr)
            std = float(np.std(pnl_arr)) if len(pnl_arr) > 1 else 1.0
            sharpe = (mean / std * (252 ** 0.5)) if std > 0 else 0.0
        else:
            sharpe = 0.0

        # Latest params from the most recent trade
        latest_params = {}
        for t in reversed(self.trades):
            snap = t.get("params_snapshot")
            if snap:
                try:
                    latest_params = json.loads(snap) if isinstance(snap, str) else snap
                    break
                except Exception:
                    pass

        # Fib-specific metrics
        fib_trades = [t for t in closed if t.get("fib_level_triggered")]
        fib_pnls = [t["pnl"] for t in fib_trades]
        fib_wins = [p for p in fib_pnls if p > 0]
        fib_win_rate = (len(fib_wins) / len(fib_pnls) * 100) if fib_pnls else None

        # Best performing Fib level
        level_pnl: dict[str, list] = {}
        for t in fib_trades:
            lbl = t.get("fib_level_triggered", "unknown")
            level_pnl.setdefault(lbl, []).append(t["pnl"])
        best_fib_level = max(level_pnl, key=lambda l: sum(level_pnl[l]), default=None) if level_pnl else None

        return {
            "total_trades": total,
            "win_rate": round(win_rate, 1),
            "win_count": win_count,
            "loss_count": total - win_count,
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "total_pnl": round(total_pnl, 2),
            "profit_factor": round(profit_factor, 3),
            "current_loss_streak": streak,
            "max_loss_streak": max_streak,
            "daily_pnl": round(daily_pnl, 2),
            "sharpe_ratio": round(sharpe, 3),
            "last_active_params": latest_params,
            # Fibonacci metrics
            "fib_trades_count": len(fib_trades),
            "fib_win_rate": round(fib_win_rate, 1) if fib_win_rate is not None else None,
            "best_fib_level": best_fib_level,
        }

    def _empty_metrics(self) -> dict:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "win_count": 0,
            "loss_count": 0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "total_pnl": 0.0,
            "profit_factor": 0.0,
            "current_loss_streak": 0,
            "max_loss_streak": 0,
            "daily_pnl": 0.0,
            "sharpe_ratio": 0.0,
            "last_active_params": {},
            # Fibonacci metrics — always present so build_prompt() never KeyErrors
            "fib_trades_count": 0,
            "fib_win_rate": None,
            "best_fib_level": None,
        }


# ─────────────────────────────────────────────
# PROMPT BUILDER
# ─────────────────────────────────────────────

def get_system_prompt() -> str:
    """Build the organism system prompt using current vital signs."""
    return vital_signs.build_organism_system_prompt()


def build_prompt(
    metrics: dict,
    current_params: dict,
    trigger: str,
    sentiment_report: str | None = None,
) -> str:
    vs = vital_signs.get_status()
    survival_directive = ""
    if vs["survival_state"] in ("WOUNDED", "ORGAN_FAILURE", "DECEASED"):
        survival_directive = (
            f"\n⚠️ SURVIVAL ALERT: Organism is {vs['survival_state']} "
            f"(drawdown={vs['drawdown_pct']:.1f}%). "
            f"PRIORITISE capital preservation. Reduce qty and tighten stops."
        )
    elif vs["apex_tier"] >= 2:
        survival_directive = (
            f"\n🦾 APEX MODE: Organism is {vs['apex_state']} "
            f"(profit={vs['profit_pct']:.1f}%). "
            f"Scale aggression — the organism has earned the right to compound."
        )

    _sentiment_block = sentiment_report or ""
    return f"""ANALYSIS TRIGGER: {trigger}{survival_directive}

{_sentiment_block}

CURRENT VITAL STATE: {vs['survival_state']} | Apex: {vs['apex_state']}

CURRENT STRATEGY PARAMETERS:
- BB Period: {current_params.get('bb_period', '?')} (bounds: 8–100)
- BB Std Dev: {current_params.get('bb_std_dev', '?')} (bounds: 1.0–3.5)
- Stop Loss %: {current_params.get('stop_loss_pct', '?')} (bounds: 0.25–5.0)
- Position Qty: {current_params.get('qty', '?')} (bounds: 1–50)
- Fib Lookback Bars: {current_params.get('fib_lookback_bars', '50')} (bounds: 20–200)
- Fib Bounce Threshold %: {current_params.get('fib_bounce_threshold_pct', '0.20')} (bounds: 0.05–1.0)
- Fib Entry Mode: {current_params.get('fib_entry_mode', 'AND')} (AND=quality, OR=quantity)

PERFORMANCE METRICS (last {metrics['total_trades']} closed trades):
- Win Rate: {metrics['win_rate']}%
- Win Count / Loss Count: {metrics['win_count']} / {metrics['loss_count']}
- Average Win: ${metrics['avg_win']:+.2f} | Average Loss: ${metrics['avg_loss']:+.2f}
- Profit Factor: {metrics['profit_factor']}
- Current Consecutive Losses: {metrics['current_loss_streak']}
- Max Loss Streak: {metrics['max_loss_streak']}
- Total Realized PnL: ${metrics['total_pnl']:+.2f}
- Daily PnL: ${metrics['daily_pnl']:+.2f}
- Sharpe-like Ratio: {metrics['sharpe_ratio']}
- Fib-Triggered Trades: {metrics.get('fib_trades_count', 0)}
- Fib Win Rate: {str(metrics.get('fib_win_rate')) + '%' if metrics.get('fib_win_rate') is not None else 'N/A (no Fib trades yet)'}
- Best Performing Fib Level: {metrics.get('best_fib_level', 'N/A')}

GOALS (adapted to current Vital State and Environmental Intelligence):
1. When WOUNDED/ORGAN_FAILURE: reduce qty to ≤50% of current; tighten stop_loss_pct
2. If win rate < 40%: widen BB bands (higher std_dev or longer period)
3. If loss streak >= 3: reduce qty, tighten stops — protect the lifeblood
4. If profit_factor > 1.5 and win_rate > 55% and HEALTHY/APEX: scale qty to compound
5. If avg_loss > 2x avg_win: shorten stop_loss_pct and widen bands
6. FIBONACCI RETRACEMENT (the organism breathes with the market):
   - If fib_win_rate < 45%: increase fib_bounce_threshold_pct (be more lenient in level detection)
     OR increase fib_lookback_bars (detect larger swings for more reliable levels)
   - If fib_win_rate > 65% and fib_trades_count > 5: decrease fib_bounce_threshold_pct (tighten entry precision)
   - If best_fib_level == '61.8%': the organism thrives at the Golden Ratio — keep it active
   - Market breathes IN (retracement) before continuing OUT (trend). Be patient at the exhale.
   - Do NOT chase price at extremes. The organism WAITS at the Fib level, then enters on the bounce.
7. REGIME INTELLIGENCE (Environmental Adaptation):
   - If market_regime == TRENDING: increase adx_trend_threshold slightly (require stronger trend to gate entry)
     AND widen bb_std_dev (only take high-deviation mean reversion pops in trending markets)
   - If market_regime == VOLATILE: increase stop_loss_pct and reduce qty (slippage risk is high)
   - If market_regime == RANGING: this is prime territory — can tighten thresholds for more entries
8. KELLY POSITION SIZING (Statistical Edge Enforcement):
   - If win_rate > 60% and profit_factor > 2.0 and total_trades > 30: increase kelly_fraction toward 0.40
   - If win_rate < 45% or current_loss_streak >= 3: decrease kelly_fraction toward 0.10 (Quarter → Eighth Kelly)
   - NEVER recommend kelly_fraction > 0.50 — even the most successful quant funds cap at Half-Kelly
   - The kelly_fraction encodes the organism's confidence in its own edge: earn it, don't borrow it.
9. VWAP INTELLIGENCE (Institutional Fair Value Calibration):
   - vwap_entry_sd controls how far from VWAP price must be before flagging a long zone
   - If win_rate < 45%: increase vwap_entry_sd toward 3.0 (only enter at extreme institutional zones)
   - If market_regime == VOLATILE or current_loss_streak >= 2: increase vwap_entry_sd (reduce false entries)
   - If win_rate > 60% and market_regime == RANGING: consider decreasing vwap_entry_sd toward 2.0
     to capture more mean-reversion opportunities at moderate VWAP stretches
   - NEVER set vwap_entry_sd below 1.5 (too many noise entries) or above 3.5 (never triggers)
   - Think of vwap_entry_sd as the organism's "patience threshold" — higher = waits for a better pitch

Respond with ONLY this JSON (no other text):
{{
  "bb_period": <integer 8-100>,
  "bb_std_dev": <float 1.0-3.5>,
  "stop_loss_pct": <float 0.25-5.0>,
  "qty": <integer 1-50>,
  "fib_lookback_bars": <integer 20-200>,
  "fib_bounce_threshold_pct": <float 0.05-1.0>,
  "adx_trend_threshold": <float 15.0-45.0>,
  "kelly_fraction": <float 0.05-0.50>,
  "vwap_entry_sd": <float 1.5-3.5>,
  "reasoning": "<2-3 sentence explanation, written as the organism protecting its lifeblood and breathing with the market>"
}}"""


# ─────────────────────────────────────────────
# STRATEGY EVOLVER
# ─────────────────────────────────────────────

class StrategyEvolver:
    """Calls OpenClaw (Gemini Flash) or Ollama to get new strategy parameters."""

    def __init__(self):
        self._openclaw_client: Optional[OpenAI] = None
        self._init_clients()
        # Field Intelligence Reporter — injected into every evolution prompt
        from sentiment_context import SentimentContextBuilder
        self._sentiment_builder = SentimentContextBuilder()

    def _init_clients(self):
        """Initialize OpenAI-compatible clients for OpenClaw."""
        try:
            cfg = config.ai_snapshot()
            self._openclaw_client = OpenAI(
                api_key=cfg["openclaw_token"],
                base_url=f"{cfg['openclaw_base_url'].rstrip('/')}/v1",
                timeout=30.0,
            )
            logger.info(
                f"OpenClaw client initialized → {cfg['openclaw_base_url']} "
                f"model={cfg['openclaw_model']}"
            )
        except Exception as e:
            logger.error(f"Failed to init OpenClaw client: {e}")

    def evolve(
        self, metrics: dict, current_params: dict, trigger: str
    ) -> dict:
        """
        Run one evolution cycle. Returns a dict with:
          - new_params: validated params dict
          - reasoning: LLM explanation
          - model_used: which model responded
          - warnings: guardrail warnings
          - applied: bool
        """
        cfg = config.ai_snapshot()

        # Build field intelligence report for the AI Brain
        vs_status = vital_signs.get_status()
        sentiment_report = None
        if config.sentiment_context_enabled:
            try:
                from strategy import engine as _engine
                _regime  = getattr(_engine, '_regime_state', None)
                _mom     = getattr(_engine, '_momentum_state', None)
                _trades  = _run_async(get_recent_trades_for_analysis("fleet", limit=20))
                sentiment_report = self._sentiment_builder.build(
                    df=None,  # df not available here; VIX proxy skipped at AI cycle time
                    regime_state=_regime,
                    momentum_state=_mom,
                    recent_trades=_trades,
                )
            except Exception as se:
                logger.warning(f"[SENTIMENT] Field intelligence build failed: {se}")

        prompt = build_prompt(metrics, current_params, trigger, sentiment_report=sentiment_report)
        system_prompt = get_system_prompt()

        # Determine model from intelligence budget (apex tier)
        budget = vital_signs.get_status()["intelligence_budget"]
        apex_model = budget.get("model", cfg["openclaw_model"])
        apex_temp = budget.get("temperature", 0.3)
        apex_tier_name = budget.get("tier_name", "HUNTING")

        logger.info(
            f"[AI Brain] Evolving as {apex_tier_name} organism. "
            f"Model: {apex_model} | Temp: {apex_temp}"
        )

        # --- Try OpenClaw (primary) ---
        raw_json, model_used = self._call_openclaw(
            prompt, cfg, system_prompt=system_prompt,
            model_override=apex_model, temperature=apex_temp,
        )

        # --- Ollama fallback ---
        if raw_json is None:
            logger.warning("OpenClaw failed, falling back to Ollama")
            raw_json, model_used = self._call_ollama_via_openclaw(
                prompt, cfg, system_prompt=system_prompt,
                model_override=budget.get("ollama_model"),
            )

        if raw_json is None:
            logger.error("Both OpenClaw and Ollama failed — skipping evolution cycle")
            return {"applied": False, "error": "All AI endpoints failed"}

        # --- Parse JSON ---
        try:
            parsed = self._extract_json(raw_json)
        except Exception as e:
            logger.error(f"JSON parse error from {model_used}: {e}\nRaw: {raw_json[:500]}")
            return {"applied": False, "error": f"JSON parse error: {e}"}

        # --- Guardrail validation ---
        try:
            validated, warnings = ParamGuardrail.validate(parsed)
        except ValueError as e:
            logger.error(f"Guardrail rejected response: {e}")
            return {"applied": False, "error": str(e)}

        reasoning = parsed.get("reasoning", "No reasoning provided.")

        # --- Apply params (core + optional survival instinct params) ---
        # Separate Kelly & regime params from standard strategy params
        survival_param_keys = {"adx_trend_threshold", "kelly_fraction", "ema_fast", "ema_mid", "ema_slow", "vwap_entry_sd"}
        strategy_params = {k: v for k, v in validated.items() if k not in survival_param_keys}
        survival_params  = {k: v for k, v in validated.items() if k in survival_param_keys}

        config.update(**strategy_params)
        if survival_params:
            config.update(**survival_params)
            logger.info(f"[AI Brain] Applied survival instinct params: {survival_params}")

        logger.info(
            f"[AI Brain] Applied new params via {model_used}: {strategy_params}\n"
            f"Reasoning: {reasoning}"
        )

        if warnings:
            for w in warnings:
                logger.warning(f"[Guardrail] {w}")

        return {
            "applied": True,
            "new_params": validated,
            "reasoning": reasoning,
            "model_used": model_used,
            "apex_tier": apex_tier_name,
            "warnings": warnings,
        }

    def _call_openclaw(
        self, prompt: str, cfg: dict,
        system_prompt: str = "",
        model_override: Optional[str] = None,
        temperature: float = 0.3,
    ) -> tuple[Optional[str], str]:
        """Call OpenClaw with the resolved model (apex-tier aware)."""
        if not self._openclaw_client:
            return None, ""
        model = model_override or cfg["openclaw_model"]
        if not system_prompt:
            system_prompt = get_system_prompt()
        try:
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
            content = response.choices[0].message.content
            return content, model
        except Exception as e:
            logger.warning(f"OpenClaw primary call failed: {e}")
            return None, ""

    def _call_ollama_via_openclaw(
        self, prompt: str, cfg: dict,
        system_prompt: str = "",
        model_override: Optional[str] = None,
    ) -> tuple[Optional[str], str]:
        """Call Ollama model via OpenClaw's proxy (apex-tier aware model)."""
        if not system_prompt:
            system_prompt = get_system_prompt()
        if not self._openclaw_client:
            return self._call_ollama_direct(prompt, cfg, system_prompt=system_prompt)
        try:
            model = model_override or cfg.get("ollama_model", "ollama/gemma4:e4b")
            response = self._openclaw_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=512,
            )
            content = response.choices[0].message.content
            return content, model
        except Exception as e:
            logger.warning(f"Ollama via OpenClaw failed: {e}, trying direct Ollama")
            return self._call_ollama_direct(prompt, cfg, system_prompt=system_prompt)

    def _call_ollama_direct(
        self, prompt: str, cfg: dict, system_prompt: str = ""
    ) -> tuple[Optional[str], str]:
        """Direct Ollama REST API call as last resort."""
        if not system_prompt:
            system_prompt = get_system_prompt()
        try:
            ollama_url = cfg.get("ollama_base_url", "http://localhost:11434")
            model = cfg.get("ollama_model_name", "gemma2:4b")
            payload = {
                "model": model,
                "prompt": f"{system_prompt}\n\n{prompt}",
                "stream": False,
                "format": "json",
            }
            resp = httpx.post(
                f"{ollama_url}/api/generate",
                json=payload,
                timeout=90.0,  # Ollama on CPU needs ~40s
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", ""), f"ollama-direct/{model}"
        except Exception as e:
            logger.error(f"Direct Ollama call failed: {e}")
            return None, ""

    @staticmethod
    def _extract_json(raw: str) -> dict:
        """Extract JSON from potentially noisy LLM output."""
        raw = raw.strip()
        # Try direct parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # Try extracting from markdown code block
        import re
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        # Try finding first {...}
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"No valid JSON found in: {raw[:200]}")


# ─────────────────────────────────────────────
# AI BRAIN SCHEDULER
# ─────────────────────────────────────────────

class AIBrainScheduler:
    """
    Daemon thread that monitors trading performance and triggers
    the StrategyEvolver at the right moments.
    """

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._evolver = StrategyEvolver()
        self._lock = threading.Lock()

        # State
        self.enabled: bool = False
        self.last_run_at: Optional[str] = None
        self.last_trigger: Optional[str] = None
        self.last_decision: Optional[dict] = None
        self.next_run_at: Optional[str] = None
        self.model_used: Optional[str] = None
        self.total_cycles: int = 0
        self._trades_processed: int = 0
        self._last_trade_count: int = 0

    def start(self):
        """Start the AI Brain background scheduler."""
        if self._thread and self._thread.is_alive():
            return

        # Capture the main event loop *now* (called from the async lifespan
        # context) so that background threads can dispatch coroutines to it.
        global _captured_main_loop
        try:
            _captured_main_loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                _captured_main_loop = asyncio.get_event_loop()
            except RuntimeError:
                _captured_main_loop = None
        logger.info(f"AI Brain captured main loop: {_captured_main_loop is not None}")

        self._stop_event.clear()
        self.enabled = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="ai-brain"
        )
        self._thread.start()
        logger.info("AI Brain scheduler started")

    def stop(self):
        """Stop the AI Brain."""
        self.enabled = False
        self._stop_event.set()
        logger.info("AI Brain scheduler stopped")

    def trigger_manual(self):
        """Force an immediate analysis cycle."""
        threading.Thread(
            target=self._run_cycle,
            args=("MANUAL",),
            daemon=True,
            name="ai-brain-manual",
        ).start()

    def get_status(self) -> dict:
        with self._lock:
            cfg = config.ai_snapshot()
            return {
                "enabled": self.enabled,
                "model": cfg["openclaw_model"],
                "fallback_model": cfg["ollama_model"],
                "openclaw_url": cfg["openclaw_base_url"],
                "last_run_at": self.last_run_at,
                "last_trigger": self.last_trigger,
                "next_run_at": self.next_run_at,
                "total_cycles": self.total_cycles,
                "last_decision": self.last_decision,
                "interval_minutes": cfg["ai_interval_minutes"],
                "min_trades_trigger": cfg["ai_min_trades_trigger"],
                "loss_streak_trigger": cfg["ai_loss_streak_trigger"],
            }

    def _run_loop(self):
        """Main scheduler loop — checks triggers every 30 seconds."""
        logger.info("AI Brain loop running")
        while not self._stop_event.is_set():
            try:
                self._check_triggers()
            except Exception as e:
                logger.error(f"AI Brain loop error: {e}", exc_info=True)
            self._stop_event.wait(30)

    def _check_triggers(self):
        """Evaluate all trigger conditions."""

        cfg = config.ai_snapshot()

        # Fetch data from Firestore via the main event loop
        trades = _run_async(get_recent_trades_for_analysis("fleet", limit=200))
        equity = _run_async(get_equity_history("fleet", limit=50))

        if not trades:
            logger.debug("No trade data available from Firestore — skipping trigger check")
            return
        if equity is None:
            equity = []

        closed = [t for t in trades if t.get("side") in ("SELL", "STOP_LOSS", "HALT")]
        total_closed = len(closed)

        # ── LOSS STREAK TRIGGER ──────────────────────────────────────────
        consecutive_losses = 0
        for t in reversed(closed):
            if t.get("pnl", 0) < 0:
                consecutive_losses += 1
            else:
                break

        if consecutive_losses >= cfg["ai_loss_streak_trigger"]:
            logger.warning(
                f"AI Brain: LOSS_STREAK trigger ({consecutive_losses} consecutive losses)"
            )
            self._run_cycle(f"LOSS_STREAK:{consecutive_losses}", trades, equity)
            return

        # ── TRADE COUNT TRIGGER ──────────────────────────────────────────
        new_trades = total_closed - self._last_trade_count
        if new_trades >= cfg["ai_min_trades_trigger"] and total_closed > 0:
            logger.info(f"AI Brain: TRADE_COUNT trigger ({new_trades} new trades)")
            self._last_trade_count = total_closed
            self._run_cycle("TRADE_COUNT", trades, equity)
            return

        # ── SCHEDULE TRIGGER ─────────────────────────────────────────────
        interval_secs = cfg["ai_interval_minutes"] * 60
        if self.last_run_at:
            last_dt = datetime.fromisoformat(self.last_run_at)
            elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
            if elapsed >= interval_secs:
                logger.info("AI Brain: SCHEDULE trigger")
                self._run_cycle("SCHEDULE", trades, equity)
                return
        else:
            # First run — only if we have enough trades
            if total_closed >= max(5, cfg["ai_min_trades_trigger"]):
                self._run_cycle("SCHEDULE:initial", trades, equity)
                return

        # Update next run estimate
        if self.last_run_at:
            last_dt = datetime.fromisoformat(self.last_run_at)
            next_dt = last_dt.timestamp() + interval_secs
            with self._lock:
                self.next_run_at = datetime.fromtimestamp(next_dt, tz=timezone.utc).isoformat()

    def _run_cycle(
        self,
        trigger: str,
        trades: Optional[list] = None,
        equity: Optional[list] = None,
    ):
        """Execute one evolution cycle synchronously."""

        now_str = datetime.now(timezone.utc).isoformat()

        # Fetch data if not provided
        if trades is None or equity is None:
            trades = _run_async(get_recent_trades_for_analysis("fleet", limit=200))
            equity = _run_async(get_equity_history("fleet", limit=50))

        # Compute metrics
        analyser = PerformanceAnalyser(trades, equity)
        metrics = analyser.compute()

        if metrics["total_trades"] == 0:
            logger.info("AI Brain: no closed trades yet, skipping cycle")
            return

        current_params = config.snapshot()
        logger.info(
            f"AI Brain: running cycle trigger={trigger} "
            f"trades={metrics['total_trades']} win_rate={metrics['win_rate']}%"
        )

        # Evolve
        result = self._evolver.evolve(metrics, current_params, trigger)

        # Persist decision
        params_before = json.dumps(current_params)
        params_after = json.dumps(result.get("new_params", {}))

        _run_async(
            save_ai_decision(
                "fleet",
                {
                    "timestamp": now_str,
                    "trigger": trigger,
                    "trades_analysed": metrics["total_trades"],
                    "win_rate_before": metrics["win_rate"],
                    "daily_pnl_before": metrics["daily_pnl"],
                    "params_before": params_before,
                    "params_after": params_after,
                    "reasoning": result.get("reasoning", ""),
                    "model_used": result.get("model_used", "unknown"),
                    "applied": 1 if result.get("applied") else 0,
                }
            )
        )

        with self._lock:
            self.last_run_at = now_str
            self.last_trigger = trigger
            self.total_cycles += 1
            self.model_used = result.get("model_used")
            self.last_decision = {
                "trigger": trigger,
                "timestamp": now_str,
                "metrics": metrics,
                "params_before": current_params,
                "params_after": result.get("new_params"),
                "reasoning": result.get("reasoning"),
                "model_used": result.get("model_used"),
                "applied": result.get("applied"),
                "warnings": result.get("warnings", []),
            }

        logger.info(f"AI Brain: cycle complete. Applied={result.get('applied')}")


# Singleton instance
ai_brain = AIBrainScheduler()
