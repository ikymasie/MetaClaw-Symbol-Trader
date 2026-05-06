# TradeClaw — Implementation Task List

This task list tracks the progress of the four-phase ATLAS Gap implementation plus the LangGraph architecture upgrade.

## Phase 1: Darwinian Agent Weights + Weighted Deliberation
- [x] Implement `DarwinianWeightStore` class in `sub_agents.py`
- [x] Add `darwinian_weight` field to `AgentVote` dataclass in `sub_agents.py`
- [x] Wire `DarwinianWeightStore` into `SubAgentPool`
- [x] Replace hardcoded weights in `deliberate()` with live Darwinian multipliers
- [x] Replace mechanical quorum threshold with weighted net-score logic
- [x] Implement outcome recording in `bot_engine.py` (`_close_position`)
- [x] Expose Darwinian weights in `get_state_snapshot()` for Situation Room UI
- [x] Add periodic weight update trigger (daily) in `fleet.py`
- [x] Fix async Firestore calls in `DarwinianWeightStore` (use `run_coroutine_threadsafe`)
- [x] Fix `save_darwinian_weights` / `load_darwinian_weights` to be per-bot in `firebase_store.py`

## Phase 2: Adversarial CRO Agent
- [x] Implement `CROAgent` class in `sub_agents.py`
- [x] Register `CROAgent` in `AGENT_CLASSES` factory
- [x] Register `SUB_AGENT_CRO` constant and valid agents in `bot_config.py`
- [x] Wire `CROAgent` adversarial review into `SubAgentPool.deliberate()`

## Phase 3: MacroAgent Veto Power (RISK_OFF Override)

- [x] Implement Macro pre-filter logic in `deliberate()` (early exit before panel loop)
- [x] Hard veto for `BUY` signals when macro sentiment < -0.6 AND confidence > 0.65
- [x] Macro veto appears in Situation Room reasoning logs with full sentiment/confidence values
- [x] SELL signals (short entries) are NOT blocked by macro pre-filter

## Phase 4: Prompt-Level Autoresearch Loop

- [x] Create `backend/prompts/` directory with 5 agent prompt `.md` files
- [x] `PromptLoader` / `_load_prompt()` helper — agent classes use file-based prompts
- [x] Add `log_agent_recommendation`, `update_agent_recommendation_outcome`, `get_agent_sharpe` to `firebase_store.py`
- [x] Implement `PromptAutoResearcher` class in `backend/prompt_autoresearcher.py`
- [x] Wire `PromptAutoResearcher` into `fleet.py` monitor loop (daily check)
- [x] Add `autoresearch_enabled: bool = False` flag to `BotConfig` (opt-in)

## Phase 5: LangGraph Deliberation Graph + Event Streaming

- [x] Add `langgraph` + `langgraph-checkpoint-sqlite` to `requirements.txt`
- [x] Create `backend/deliberation_graph.py` — typed `StateGraph` wrapping the deliberation protocol
  - Nodes: watchman, ict, macro_prefilter, panel, cro, quorum, risk_manager, finalize
  - Conditional edges handle veto / degraded / no-quorum early exits
  - Each node runs existing sync agent code via `asyncio.to_thread()`
  - `astream_events()` streams per-node events to the per-bot event queue
- [x] Add `_event_queue` (stdlib `queue.Queue`) to `SubAgentPool` for thread-safe event delivery
- [x] Add `_get_deliberation_graph()` lazy initialiser to `SubAgentPool`
- [x] Wire LangGraph bridge into `SubAgentPool.deliberate()` with sync→async via `run_coroutine_threadsafe`
- [x] Set module-level `_main_event_loop` in `sub_agents.py` from `main.py` lifespan
- [x] PositionSizer Integration: Modify `position_sizer.py` to accept the `hunger_multiplier` and bypass the `MIN_TRADES_FOR_KELLY` limit when the hunger multiplier is active.
- [x] Strategy Loop Update: Update `strategy.py` to pass the `hunger_multiplier` into the `PositionSizer.get_qty` call.
- [x] Update `ws_fleet_broadcast_loop` in `main.py` to drain per-bot event queues each tick
- [x] Update `useAgentStream.ts` to handle `deliberation_event` messages (agent_start/agent_done/quorum_result/final_decision)
- [x] Surface live Darwinian weights in Situation Room via `agent_weights` field on `bot_update`

## Verification & Testing

- [x] **Darwinian Weights**: Verify weights stay within [0.3, 2.5] bounds over 100 cycles
- [x] **Deliberation regression**: Weighted score with all agents at weight 1.0 matches old quorum logic
- [ ] **CRO Agent**: VETO fires with 2+ structural objections; passes cleanly with none
- [ ] **Macro Veto (Phase 3)**: BUY blocked at sentiment=-0.7/confidence=0.8; SELL allowed
- [ ] **Macro Veto (Phase 3)**: BUY allowed at sentiment=-0.4 (below threshold)
- [ ] **LangGraph graph**: Imports cleanly; falls back gracefully when `langgraph` not installed
- [ ] **Event streaming**: `deliberation_event` messages appear in WS client during active deliberation
- [ ] **Autoresearch**: Git branch creation, Sharpe eval, merge/revert flow on local repo
- [ ] **Prompt files**: `_load_prompt("macro")` returns correct system + user_template content
