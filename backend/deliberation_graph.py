"""
TradeClaw — LangGraph Deliberation Graph
==========================================
Wraps the multi-agent deliberation protocol in a typed LangGraph StateGraph.

Architecture improvements over the direct SubAgentPool.deliberate() path:
  • Typed state  — all intermediate deliberation state is explicit and inspectable
  • Event streaming — astream_events() pushes granular per-node events to the
    Situation Room WebSocket clients (agent_start → agent_done → quorum → decision)
  • Checkpoint-ready — compile with AsyncSqliteSaver for full audit trail (Phase 5)
  • Human-in-the-loop — add interrupt_before=["risk_manager"] for manual review

Graph topology (linear with conditional early exits):
  START → watchman → [veto?] → ict → macro_prefilter → [veto?]
        → panel → [degraded/veto?] → cro → [veto?]
        → quorum → [no quorum?] → risk_manager → finalize → END

Each node is an async method of DeliberationGraph that calls the existing synchronous
agent code via asyncio.to_thread(), so no changes are needed to the agents themselves.
"""

from __future__ import annotations

import asyncio
import logging
import operator
import queue as _stdlib_queue
import time
from typing import Annotated, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sub_agents import SubAgentPool

logger = logging.getLogger("tradeclaw.deliberation_graph")

try:
    from langgraph.graph import StateGraph, START, END
    from typing_extensions import TypedDict
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    logger.warning("langgraph not installed — LangGraph path disabled")


# ─────────────────────────────────────────────
# TYPED STATE
# ─────────────────────────────────────────────

if LANGGRAPH_AVAILABLE:
    class DeliberationState(TypedDict):
        # ── Inputs (immutable after graph start) ──────────────────────
        bot_id: str
        raw_signal: str
        requested_qty: int
        equity: float
        daily_pnl: float
        starting_equity: float
        max_daily_drawdown_pct: float
        recent_trades: list
        survival_state: str
        signal_price: float
        vote_cache_ttl: int
        enabled_agents: list

        # ── Accumulated state (reducer: append-only lists) ─────────────
        votes: Annotated[list, operator.add]
        veto_agents: Annotated[list, operator.add]
        failed_agents: Annotated[list, operator.add]

        # ── Decision state ─────────────────────────────────────────────
        weighted_score: float
        quorum_met: bool
        approved_qty: int
        exit_reason: str   # "pending" | "veto" | "degraded" | "no_quorum" | "approved"

# Map LangGraph node names → frontend agent identifiers
_NODE_TO_AGENT: dict[str, str] = {
    "watchman":        "watchman",
    "ict":             "ict",
    "macro_prefilter": "macro",
    "panel":           "panel",
    "cro":             "cro",
    "risk_manager":    "risk_manager",
}


# ─────────────────────────────────────────────
# DELIBERATION GRAPH
# ─────────────────────────────────────────────

class DeliberationGraph:
    """
    LangGraph-powered deliberation engine for one bot.
    Wraps the existing agent logic in a typed StateGraph with event streaming.
    """

    def __init__(self, pool: "SubAgentPool"):
        self._pool = pool
        self.bot_id = pool.bot_id
        self._logger = logging.getLogger(f"tradeclaw.graph[{pool.bot_id}]")
        self._compiled = None   # Compiled graph (built lazily)

    # ─────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────

    async def arun(
        self,
        state: dict,
        event_queue: Optional[_stdlib_queue.Queue] = None,
        price_history=None,
    ) -> Optional["TradeDecision"]:
        """
        Execute the deliberation graph and return a TradeDecision.
        Events are pushed to event_queue as each node completes.
        Returns None if LangGraph is unavailable or the graph fails.
        """
        if not LANGGRAPH_AVAILABLE:
            return None

        graph = self._get_compiled()
        if graph is None:
            return None

        # Attach runtime-only refs to pool (not serialised to state)
        self._price_history = price_history
        self._event_queue = event_queue

        # Build initial state with reducer defaults
        initial: DeliberationState = {
            **state,
            "votes": [],
            "veto_agents": [],
            "failed_agents": [],
            "weighted_score": 0.0,
            "quorum_met": False,
            "approved_qty": 0,
            "exit_reason": "pending",
        }

        config = {"configurable": {"thread_id": f"delib-{self.bot_id}"}}

        try:
            final_decision: Optional["TradeDecision"] = None

            async for event in graph.astream_events(initial, config=config, version="v2"):
                self._handle_stream_event(event)
                if event["event"] == "on_chain_end" and event.get("name") == "finalize":
                    output = event.get("data", {}).get("output", {})
                    final_decision = output.get("__decision__")

            return final_decision

        except Exception as e:
            self._logger.error(f"Graph execution failed: {e}", exc_info=True)
            return None

    # ─────────────────────────────────────────────
    # GRAPH CONSTRUCTION
    # ─────────────────────────────────────────────

    def _get_compiled(self):
        if self._compiled is None:
            self._compiled = self._build_graph()
        return self._compiled

    def _build_graph(self):
        if not LANGGRAPH_AVAILABLE:
            return None
        try:
            g = StateGraph(DeliberationState)

            g.add_node("watchman",        self._watchman_node)
            g.add_node("ict",             self._ict_node)
            g.add_node("macro_prefilter", self._macro_prefilter_node)
            g.add_node("panel",           self._panel_node)
            g.add_node("cro",             self._cro_node)
            g.add_node("quorum",          self._quorum_node)
            g.add_node("risk_manager",    self._risk_manager_node)
            g.add_node("finalize",        self._finalize_node)

            g.add_edge(START, "watchman")
            g.add_conditional_edges("watchman",        self._route_veto,   {"continue": "ict",            "finalize": "finalize"})
            g.add_edge("ict", "macro_prefilter")
            g.add_conditional_edges("macro_prefilter", self._route_veto,   {"continue": "panel",          "finalize": "finalize"})
            g.add_conditional_edges("panel",           self._route_panel,  {"continue": "cro",            "finalize": "finalize"})
            g.add_conditional_edges("cro",             self._route_veto,   {"continue": "quorum",         "finalize": "finalize"})
            g.add_conditional_edges("quorum",          self._route_quorum, {"continue": "risk_manager",   "finalize": "finalize"})
            g.add_edge("risk_manager", "finalize")
            g.add_edge("finalize", END)

            return g.compile()
        except Exception as e:
            self._logger.error(f"Graph build failed: {e}")
            return None

    # ─────────────────────────────────────────────
    # ROUTING FUNCTIONS
    # ─────────────────────────────────────────────

    def _route_veto(self, state: DeliberationState) -> str:
        return "finalize" if state.get("veto_agents") else "continue"

    def _route_panel(self, state: DeliberationState) -> str:
        if state.get("veto_agents"):
            return "finalize"
        enabled_panel = [a for a in ["sentiment", "macro", "earnings", "technical"]
                         if a in state["enabled_agents"]]
        failed = state.get("failed_agents", [])
        if enabled_panel and len(failed) > len(enabled_panel) / 2:
            return "finalize"  # Degraded quorum
        return "continue"

    def _route_quorum(self, state: DeliberationState) -> str:
        return "continue" if state.get("quorum_met") else "finalize"

    # ─────────────────────────────────────────────
    # NODE IMPLEMENTATIONS
    # ─────────────────────────────────────────────

    async def _watchman_node(self, state: DeliberationState) -> dict:
        from sub_agents import WatchmanAgent, AgentVote
        self._emit("agent_start", "watchman")
        try:
            agent = WatchmanAgent(**self._agent_kwargs())
            vote: AgentVote = await asyncio.to_thread(
                agent.get_vote, price_history=self._price_history
            )
            self._emit("agent_done", "watchman",
                       vote=vote.vote, confidence=vote.confidence,
                       reasoning=vote.reasoning[:120])
            veto = [vote.agent] if vote.vote == "VETO" else []
            return {"votes": [vote.to_dict()], "veto_agents": veto}
        except Exception as e:
            self._logger.warning(f"Watchman node error: {e}")
            return {}

    async def _ict_node(self, state: DeliberationState) -> dict:
        if "ict" not in state["enabled_agents"]:
            return {}
        from sub_agents import ICTAgent
        self._emit("agent_start", "ict")
        try:
            agent = ICTAgent(**self._agent_kwargs())
            vote = await asyncio.to_thread(agent.get_vote, price_history=self._price_history)
            self._emit("agent_done", "ict", vote=vote.vote, confidence=vote.confidence,
                       reasoning=vote.reasoning[:120])
            return {"votes": [vote.to_dict()]}
        except Exception as e:
            self._logger.warning(f"ICT node error: {e}")
            return {}

    async def _macro_prefilter_node(self, state: DeliberationState) -> dict:
        """Fast RISK_OFF gate — uses cached macro signal, exits early if threshold crossed."""
        SENTIMENT_THRESHOLD  = -0.6
        CONFIDENCE_THRESHOLD = 0.65

        if "macro" not in state["enabled_agents"] or state["raw_signal"] != "BUY":
            return {}

        from sub_agents import AgentVote, build_agent
        self._emit("agent_start", "macro_prefilter")

        pool = self._pool
        with pool._lock:
            macro_sig = pool.latest_signals.get("macro")
        age = time.time() - pool._vote_timestamps.get("macro", 0)

        if macro_sig is None or age > state["vote_cache_ttl"]:
            try:
                agent = build_agent(agent_name="macro", **self._agent_kwargs())
                if agent:
                    macro_sig = await asyncio.to_thread(agent.run)
                    with pool._lock:
                        pool.latest_signals["macro"] = macro_sig
                    pool._vote_timestamps["macro"] = time.time()
            except Exception as e:
                self._logger.warning(f"Macro prefilter refresh: {e}")

        if (macro_sig is not None
                and macro_sig.sentiment < SENTIMENT_THRESHOLD
                and macro_sig.confidence > CONFIDENCE_THRESHOLD):
            vote = AgentVote(
                agent="macro", vote="VETO",
                confidence=macro_sig.confidence,
                reasoning=(
                    f"MACRO RISK_OFF PRE-FILTER: sentiment={macro_sig.sentiment:.2f} "
                    f"(threshold {SENTIMENT_THRESHOLD}). {macro_sig.reasoning[:150]}"
                ),
                weight=2.0,
                veto_reason=f"Macro RISK_OFF (sentiment={macro_sig.sentiment:.2f})",
            )
            self._emit("agent_done", "macro", vote="VETO", confidence=macro_sig.confidence,
                       reasoning=vote.reasoning[:120])
            return {"votes": [vote.to_dict()], "veto_agents": ["macro"],
                    "exit_reason": "macro_prefilter_veto"}

        self._emit("agent_done", "macro_prefilter", vote="PASS", confidence=0.0, reasoning="")
        return {}

    async def _panel_node(self, state: DeliberationState) -> dict:
        """Run the 4 LLM panel agents concurrently via asyncio.gather."""
        from sub_agents import AgentVote, build_agent, AgentSignal

        panel_agents = ["sentiment", "macro", "earnings", "technical"]
        enabled = [a for a in panel_agents if a in state["enabled_agents"]]
        if not enabled:
            return {}

        self._emit("agent_start", "panel")

        pool = self._pool
        _static_w = {"sentiment": 1.0, "macro": 1.0, "earnings": 1.5, "technical": 0.75}
        with pool._lock:
            cached = dict(pool.latest_signals)
        timestamps = dict(pool._vote_timestamps)

        async def _run_one(agent_name: str) -> Optional[AgentSignal]:
            sig = cached.get(agent_name)
            age = time.time() - timestamps.get(agent_name, 0)
            if sig is None or age > state["vote_cache_ttl"]:
                try:
                    agent = build_agent(agent_name=agent_name, **self._agent_kwargs())
                    if agent:
                        sig = await asyncio.to_thread(agent.run)
                        with pool._lock:
                            pool.latest_signals[agent_name] = sig
                        pool._vote_timestamps[agent_name] = time.time()
                except Exception as e:
                    self._logger.warning(f"Panel agent {agent_name} failed: {e}")
                    return None
            return sig

        results = await asyncio.gather(*[_run_one(a) for a in enabled], return_exceptions=False)

        votes: list[dict] = []
        veto_agents: list[str] = []
        failed: list[str] = []
        raw_signal = state["raw_signal"]

        for agent_name, sig in zip(enabled, results):
            if sig is None:
                failed.append(agent_name)
                continue
            if sig.confidence < 0.05:
                continue

            if sig.confidence < 0.1:
                vote_str = "HOLD"
            elif sig.sentiment > 0.15:
                vote_str = "BUY"
            elif sig.sentiment < -0.15:
                vote_str = "SELL"
            else:
                vote_str = "HOLD"

            if agent_name == "earnings" and sig.sentiment < -0.7 and sig.confidence > 0.6:
                vote_str = "VETO"
            if agent_name == "macro" and raw_signal == "BUY" and sig.sentiment < -0.6 and sig.confidence > 0.6:
                vote_str = "VETO"

            vote = AgentVote(
                agent=agent_name, vote=vote_str,
                confidence=sig.confidence,
                reasoning=sig.reasoning[:200],
                weight=_static_w.get(agent_name, 1.0),
                darwinian_weight=pool._darwin.get_weight(agent_name),
                veto_reason=sig.reasoning[:120] if vote_str == "VETO" else None,
            )
            votes.append(vote.to_dict())
            if vote_str == "VETO":
                veto_agents.append(agent_name)

            self._emit("agent_done", agent_name, vote=vote_str,
                       confidence=sig.confidence, reasoning=sig.reasoning[:100])

        return {"votes": votes, "veto_agents": veto_agents, "failed_agents": failed}

    async def _cro_node(self, state: DeliberationState) -> dict:
        if "cro" not in state["enabled_agents"] or state.get("veto_agents"):
            return {}
        from sub_agents import CROAgent
        self._emit("agent_start", "cro")
        pool = self._pool
        try:
            agent = CROAgent(**self._agent_kwargs())
            agent._darwin_weight = pool._darwin.get_weight("cro")
            with pool._lock:
                macro_sig = pool.latest_signals.get("macro")

            from sub_agents import AgentVote as _AV
            panel_votes = [_AV(**{k: v for k, v in vd.items()
                                  if k in _AV.__dataclass_fields__})
                           for vd in state.get("votes", [])
                           if vd.get("agent") not in ("watchman", "ict", "risk_manager")]
            vote = await asyncio.to_thread(
                agent.get_vote,
                raw_signal=state["raw_signal"],
                symbol=pool.symbol,
                panel_votes=panel_votes,
                macro_signal=macro_sig,
                price_history=self._price_history,
            )
            vote.darwinian_weight = pool._darwin.get_weight("cro")
            self._emit("agent_done", "cro", vote=vote.vote, confidence=vote.confidence,
                       reasoning=vote.reasoning[:120])
            veto = [vote.agent] if vote.vote == "VETO" else []
            return {"votes": [vote.to_dict()], "veto_agents": veto}
        except Exception as e:
            self._logger.warning(f"CRO node error: {e}")
            return {}

    async def _quorum_node(self, state: DeliberationState) -> dict:
        self._emit("quorum_calc", "quorum")
        raw_signal = state["raw_signal"]
        panel_votes = [v for v in state.get("votes", [])
                       if v.get("agent") not in ("risk_manager", "watchman", "ict")]
        total_panel = len(panel_votes)

        if total_panel == 0:
            self._emit("quorum_result", "quorum", score=0.5, met=True)
            return {"weighted_score": 0.5, "quorum_met": True}

        total_w = sum(v.get("weight", 1.0) * v.get("darwinian_weight", 1.0)
                      for v in panel_votes) or 1.0
        weighted_score = sum(
            v.get("weight", 1.0) * v.get("darwinian_weight", 1.0) * v.get("confidence", 0.0)
            * (1 if v.get("vote") == raw_signal
               else -1 if v.get("vote") not in ("HOLD", "VETO") else 0)
            for v in panel_votes
        ) / total_w

        quorum_met = weighted_score >= 0.25
        self._emit("quorum_result", "quorum", score=round(weighted_score, 3), met=quorum_met)

        if not quorum_met:
            return {"weighted_score": round(weighted_score, 3), "quorum_met": False,
                    "exit_reason": "no_quorum"}
        return {"weighted_score": round(weighted_score, 3), "quorum_met": True}

    async def _risk_manager_node(self, state: DeliberationState) -> dict:
        from sub_agents import RiskManagerAgent
        self._emit("agent_start", "risk_manager")
        pool = self._pool
        try:
            agent = RiskManagerAgent(**self._agent_kwargs())
            vote, approved_qty = await asyncio.to_thread(
                agent.get_vote,
                signal=state["raw_signal"],
                requested_qty=state["requested_qty"],
                equity=state["equity"],
                daily_pnl=state["daily_pnl"],
                starting_equity=state["starting_equity"],
                max_daily_drawdown_pct=state["max_daily_drawdown_pct"],
                recent_trades=state["recent_trades"],
                survival_state=state["survival_state"],
            )
            self._emit("agent_done", "risk_manager", vote=vote.vote,
                       confidence=vote.confidence, reasoning=vote.reasoning[:120])
            veto = [vote.agent] if vote.vote == "VETO" else []
            return {"votes": [vote.to_dict()], "veto_agents": veto,
                    "approved_qty": approved_qty}
        except Exception as e:
            self._logger.warning(f"RiskManager node error: {e}")
            return {"veto_agents": ["risk_manager"], "approved_qty": 0,
                    "exit_reason": "risk_manager_error"}

    async def _finalize_node(self, state: DeliberationState) -> dict:
        """Build the canonical TradeDecision from accumulated graph state."""
        from sub_agents import TradeDecision

        veto_agents = state.get("veto_agents", [])
        exit_reason = state.get("exit_reason", "pending")
        weighted_score = state.get("weighted_score", 0.0)
        approved_qty = state.get("approved_qty", 0)
        votes = state.get("votes", [])
        raw_signal = state["raw_signal"]
        quorum_met = state.get("quorum_met", False)
        failed = state.get("failed_agents", [])

        # Determine approval
        panel_votes = [v for v in votes if v.get("agent") not in
                       ("risk_manager", "watchman", "ict", "cro")]
        total_panel = len(panel_votes)
        agree_count = sum(1 for v in panel_votes if v.get("vote") == raw_signal)

        if veto_agents:
            approved = False
            reasoning = f"VETO issued by: {', '.join(veto_agents)}"
        elif exit_reason == "degraded" or (
            total_panel > 0 and len(failed) > total_panel / 2
        ):
            approved = False
            reasoning = (
                f"Quorum degraded: {len(failed)}/{total_panel} panel agents failed "
                f"({', '.join(failed)}). Trade blocked for safety."
            )
        elif not quorum_met:
            approved = False
            reasoning = (
                f"Quorum failed: {agree_count}/{total_panel} agents agree, "
                f"weighted_score={weighted_score:.3f}."
            )
        else:
            approved = True
            avg_conf = (sum(v.get("confidence", 0.0) for v in panel_votes) / total_panel
                        if total_panel else 0.5)
            urgency = "HIGH" if avg_conf >= 0.70 and agree_count == total_panel else "LOW"
            reasoning = (
                f"APPROVED: {agree_count}/{total_panel} agents agree, "
                f"score={weighted_score:.3f}, qty={approved_qty}, urgency={urgency}."
            )

        urgency = "HIGH" if approved and "HIGH" in reasoning else "LOW"

        decision = TradeDecision(
            approved=approved,
            signal=raw_signal,
            approved_qty=approved_qty if approved else 0,
            order_urgency=urgency,
            quorum_score=round(weighted_score, 3),
            votes=votes,
            veto_agents=veto_agents,
            reasoning=reasoning,
        )

        self._emit("final_decision", "finalize",
                   approved=approved, signal=raw_signal,
                   reasoning=reasoning[:200])

        # __decision__ is a non-state side-channel for arun() to extract the result
        return {"exit_reason": "approved" if approved else exit_reason or "blocked",
                "__decision__": decision}

    # ─────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────

    def _agent_kwargs(self) -> dict:
        pool = self._pool
        return dict(
            bot_id=pool.bot_id,
            symbol=pool.symbol,
            openclaw_client=pool._openclaw_client,
            openclaw_model=pool._openclaw_model,
            ollama_base_url=pool._ollama_base_url,
            ollama_model=pool._ollama_model,
        )

    def _emit(self, event_type: str, node: str, **kwargs) -> None:
        """Push a lightweight event to the per-bot event queue (non-blocking)."""
        if not self._event_queue:
            return
        try:
            self._event_queue.put_nowait({
                "type": "deliberation_event",
                "bot_id": self.bot_id,
                "event": event_type,
                "node": node,
                **kwargs,
            })
        except _stdlib_queue.Full:
            pass  # Drop if consumer is lagging — never block the deliberation

    def _handle_stream_event(self, event: dict) -> None:
        """
        Process a raw LangGraph astream_events event.
        on_chain_start → emit agent_start if recognised node
        on_chain_end   → nothing (nodes emit their own events via _emit)
        """
        etype = event.get("event", "")
        name = event.get("name", "")
        if etype == "on_chain_start" and name in _NODE_TO_AGENT:
            agent = _NODE_TO_AGENT[name]
            self._emit("agent_start", name, agent=agent)
