"""
TradeClaw — Position Reviewer (Tier-2 "human" narrator)
=======================================================
The throttled LLM layer that reasons about OPEN positions the way a disciplined
human trader would — "Why am I still in this trade? Is the thesis intact?" — and
emits a one-shot verdict the exit scanner consumes non-blocking.

This is NEVER on the 5s hot path: reviews run in a worker thread and the engine
only ever reads a cached verdict. All calls are budget-gated (shared with the
sub-agents) with an Ollama fallback; an exhausted budget simply skips the review
and the deterministic discipline guards keep protecting the position.

SAFETY: the verdict enum has only {CUT_NOW, TIGHTEN, HOLD, GIVE_ROOM} — there is
no "widen" or "remove stop" member. GIVE_ROOM defers PROFIT-side exits only; the
predefined hard stop always fires regardless. The narrator can make exits
stricter or let a thesis-intact winner run, never loosen the loss-side stop.
"""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

import httpx

from gemini_budget import gemini_budget

logger = logging.getLogger("tradeclaw.position_reviewer")

VALID_RECS = {"CUT_NOW", "TIGHTEN", "HOLD", "GIVE_ROOM"}


@dataclass
class ReviewVerdict:
    recommendation: str        # CUT_NOW | TIGHTEN | HOLD | GIVE_ROOM
    rationale: str = ""
    confidence: float = 0.0
    invalidation_price: float = 0.0


class PositionReviewer:
    """One per bot. Mirrors SubAgentPool's LLM plumbing but write-only to exits."""

    TIMEOUT_SECONDS = 30

    def __init__(self, bot_id: str, symbol: str, openclaw_client=None,
                 openclaw_model: str = "deepseek-v4-flash",
                 ollama_base_url: str = "", ollama_model: str = "",
                 vital_signs=None):
        self.bot_id = bot_id
        self.symbol = symbol
        self._openclaw_client = openclaw_client
        self._openclaw_model = openclaw_model
        self._ollama_base_url = ollama_base_url
        self._ollama_model = ollama_model
        self._vital_signs = vital_signs
        self._logger = logging.getLogger(f"tradeclaw.reviewer[{bot_id}]")
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix=f"rv-{bot_id[:6]}")
        self._pending: set = set()        # tickets with an in-flight review
        self._pending_lock = threading.Lock()

    # ── Dispatch (called from the engine tick — never blocks) ───────────
    def maybe_review(self, engine, now: float) -> None:
        """Scan tracked positions and enqueue LLM work where due. Returns
        immediately; verdicts are applied from the worker thread."""
        cfg = engine.config
        if not getattr(cfg, "psych_review_enabled", False):
            return
        interval = float(getattr(cfg, "psych_review_interval_secs", 300) or 300)
        adverse = float(getattr(cfg, "psych_review_adverse_usd", 0.0) or 0.0)
        try:
            states = list(engine._discipline._states.values())
        except Exception:
            return
        for st in states:
            ticket = st.ticket
            with self._pending_lock:
                if ticket in self._pending:
                    continue
            due_thesis = not st.exit_thesis
            due_periodic = (now - st.last_review_ts) >= interval
            due_adverse = adverse > 0 and st.mae_usd <= -abs(adverse) and (now - st.last_review_ts) >= 30
            if not (due_thesis or due_periodic or due_adverse):
                continue
            st.last_review_ts = now
            with self._pending_lock:
                self._pending.add(ticket)
            try:
                self._executor.submit(self._worker, engine, ticket, due_thesis)
            except Exception as e:
                with self._pending_lock:
                    self._pending.discard(ticket)
                self._logger.debug(f"[{self.bot_id}] review submit failed: {e}")

    def _worker(self, engine, ticket: int, set_thesis: bool) -> None:
        try:
            st = engine._discipline.get(ticket)
            if st is None:
                return
            regime = getattr(engine, "current_regime", "UNKNOWN")
            if set_thesis:
                seed = self.set_exit_thesis(st, regime)
                engine._discipline.set_thesis(
                    ticket, exit_thesis=seed.get("exit_thesis", ""),
                    invalidation_price=seed.get("invalidation_price", 0.0),
                )
                # Stamp the rationale for the UI even on the seeding pass.
                if seed.get("exit_thesis"):
                    engine.apply_position_review(
                        ticket, "HOLD", 1.0, seed["exit_thesis"], 0.0)
                return
            verdict = self.review_position(st, st.last_net, st.last_price, regime)
            tighten_factor = 0.5 if verdict.recommendation == "TIGHTEN" else 1.0
            engine.apply_position_review(
                ticket, verdict.recommendation, tighten_factor,
                verdict.rationale, verdict.invalidation_price)
        except Exception as e:
            self._logger.debug(f"[{self.bot_id}] review worker error t={ticket}: {e}")
        finally:
            with self._pending_lock:
                self._pending.discard(ticket)

    # ── LLM-backed reasoning ────────────────────────────────────────────
    def set_exit_thesis(self, state, regime: str) -> dict:
        """One-shot on first sight of a position: capture WHY we are in the trade
        and the structural level that would invalidate it (so the deterministic
        guard can act even between reviews)."""
        sys = (
            "You are a disciplined trader defining the exit plan for a position you "
            "JUST opened. Entry and exit criteria must be set BEFORE managing the "
            "trade. Respond ONLY with a JSON object: "
            '{"exit_thesis": "<one sentence: why this trade and what would end it>", '
            '"invalidation_price": <number or 0>}'
        )
        prompt = (
            f"Symbol: {self.symbol} | Side: {state.side} | Entry: {state.entry_price} | "
            f"Regime: {regime}. Give the exit thesis and a single price level that, if "
            f"crossed, means the idea is wrong. For a LONG the level is BELOW entry; for "
            f"a SHORT it is ABOVE entry. Use 0 if no clean level."
        )
        raw = self._call_llm(sys, prompt)
        out = {"exit_thesis": "", "invalidation_price": 0.0}
        data = _parse_json(raw)
        if not data:
            return out
        out["exit_thesis"] = str(data.get("exit_thesis", ""))[:240]
        inval = _to_float(data.get("invalidation_price", 0.0))
        # Safety: only accept an invalidation level on the correct (loss) side of
        # entry — never let a hallucinated number sit on the profit side.
        if inval > 0 and state.entry_price > 0:
            if state.side == "LONG" and inval < state.entry_price:
                out["invalidation_price"] = inval
            elif state.side == "SHORT" and inval > state.entry_price:
                out["invalidation_price"] = inval
        return out

    def review_position(self, state, net_profit: float, current_price: float,
                        regime: str) -> ReviewVerdict:
        """Periodic / adverse-event review of a live position."""
        sys = (
            "You are a disciplined trader monitoring an OPEN position. Ask 'Why am I "
            "still in this trade?'. Rules you must honour: be strict with losers and "
            "loose with winners; never average down; the stop is sacred. You may make "
            "the exit STRICTER or let a thesis-intact WINNER run — you may NEVER widen "
            "or remove the stop. Respond ONLY with JSON: "
            '{"recommendation": "CUT_NOW|TIGHTEN|HOLD|GIVE_ROOM", '
            '"rationale": "<one sentence>", "confidence": <0..1>}'
        )
        prompt = (
            f"Symbol: {self.symbol} | Side: {state.side} | Entry: {state.entry_price} | "
            f"Now: {current_price} | Net P/L: ${net_profit:.2f} | Worst (MAE): "
            f"${state.mae_usd:.2f} | Peak: ${state.peak_net:.2f} | Regime: {regime}. "
            f"Thesis: {state.exit_thesis or 'n/a'}. "
            f"CUT_NOW if the thesis is broken or it is a loser going nowhere; TIGHTEN to "
            f"protect a winner showing weakness; GIVE_ROOM only for a clearly-intact "
            f"winner; HOLD otherwise."
        )
        raw = self._call_llm(sys, prompt)
        data = _parse_json(raw)
        if not data:
            return ReviewVerdict("HOLD", "no review available", 0.0)
        rec = str(data.get("recommendation", "HOLD")).upper().strip()
        if rec not in VALID_RECS:
            rec = "HOLD"
        return ReviewVerdict(
            recommendation=rec,
            rationale=str(data.get("rationale", ""))[:240],
            confidence=_to_float(data.get("confidence", 0.0)),
        )

    # ── LLM transport (budget-gated OpenClaw → Ollama fallback) ─────────
    def _call_llm(self, system: str, prompt: str) -> Optional[str]:
        temperature = 0.3
        if self._vital_signs is not None:
            try:
                budget = self._vital_signs._get_intelligence_budget(
                    __import__("bot_vital_signs").APEX_TIERS[self._vital_signs.apex_tier])
                temperature = float(budget.get("temperature", 0.3))
            except Exception:
                pass
        # OpenClaw (budget-gated)
        if self._openclaw_client is not None and gemini_budget.can_call():
            model = gemini_budget.get_recommended_model(self._openclaw_model)
            if "/" in model:
                model = model.split("/", 1)[1]
            if "json" not in (system + prompt).lower():
                system = f"{system}\nRespond ONLY with a single valid JSON object."
            try:
                resp = self._openclaw_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_tokens=256,
                    response_format={"type": "json_object"},
                    timeout=self.TIMEOUT_SECONDS,
                )
                tokens = 256
                try:
                    tokens = int(getattr(resp.usage, "completion_tokens", 0)) or 256
                except Exception:
                    pass
                gemini_budget.record_call(model=model, tokens=tokens)
                return resp.choices[0].message.content
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    gemini_budget.record_429()
                self._logger.debug(f"[{self.bot_id}] OpenClaw review failed: {e}")
        # Ollama fallback
        return self._call_ollama(system, prompt)

    def _call_ollama(self, system: str, prompt: str) -> Optional[str]:
        if not self._ollama_base_url or not self._ollama_model:
            return None
        try:
            resp = httpx.post(
                f"{self._ollama_base_url}/api/generate",
                json={"model": self._ollama_model,
                      "prompt": f"{system}\n\n{prompt}",
                      "stream": False, "format": "json"},
                timeout=self.TIMEOUT_SECONDS,
            )
            if resp.status_code == 200:
                return resp.json().get("response")
        except Exception as e:
            self._logger.debug(f"[{self.bot_id}] Ollama review failed: {e}")
        return None

    def shutdown(self) -> None:
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass


def _parse_json(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    try:
        s = raw.strip()
        if s.startswith("```"):
            s = s.split("```", 2)[1] if "```" in s[3:] else s.strip("`")
            s = s.replace("json", "", 1).strip() if s.lower().startswith("json") else s
        i, j = s.find("{"), s.rfind("}")
        if i >= 0 and j > i:
            s = s[i:j + 1]
        return json.loads(s)
    except Exception:
        return None


def _to_float(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0
