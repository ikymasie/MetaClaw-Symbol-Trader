"""
TradeClaw — Prompt-Level Autoresearch
=======================================
Weekly cycle that evolves agent prompts (not parameters) using git branches.

Inspired by ATLAS autoresearch. The prompt is the intelligence.
Each week:
  1. Identify worst-performing agent (lowest rolling Sharpe over 60 days).
  2. Generate ONE targeted prompt modification via LLM.
  3. git checkout -b autoresearch/<agent>-<date>
  4. Write modified prompt to prompts/<agent>_agent.md.
  5. Run for 5 trading days.
  6. Compare new Sharpe vs baseline.
  7. git merge (kept) or git checkout main + branch delete (reverted).
"""

import subprocess
import logging
import os
from datetime import datetime, timezone
from typing import Optional
from openai import OpenAI
from prompt_loader import load_agent_prompt

logger = logging.getLogger("tradeclaw.autoresearch")


AUTORESEARCH_CYCLE_DAYS = 7      # Run once per week
EVALUATION_PERIOD_DAYS  = 5      # 5 trading days per branch
MIN_SHARPE_SAMPLE       = 20     # Minimum recommendations to compute meaningful Sharpe


class PromptAutoResearcher:
    """
    Manages the weekly prompt autoresearch cycle for one bot.
    Can be run as a daemon thread or triggered manually.
    """

    def __init__(self, bot_id: str, openclaw_client: OpenAI, openclaw_model: str):
        self.bot_id = bot_id
        self._client = openclaw_client
        self._model  = openclaw_model
        self._logger = logging.getLogger(f"tradeclaw.autoresearch[{bot_id}]")
        self._active_branch: Optional[str] = None
        self._branch_agent:  Optional[str] = None
        self._branch_start:  Optional[datetime] = None
        self._baseline_sharpe: float = 0.0

    def run_cycle(self):
        """
        Called by the fleet monitor weekly. Determines whether to:
          A) Start a new branch (if no active branch)
          B) Evaluate an existing branch (if past the evaluation period)
          C) Do nothing (still within evaluation period)
        """
        if self._active_branch is None:
            self._start_new_branch()
        elif self._evaluation_complete():
            self._evaluate_and_decide()

    # ── Branch lifecycle ─────────────────────────────────────────────

    def _start_new_branch(self):
        """Identify worst agent, generate prompt modification, create git branch."""
        from postgres_store import get_agent_sharpe
        import asyncio

        # Step 1: Find worst-performing agent
        agents = ["sentiment", "macro", "earnings", "technical", "cro"]
        sharpes = {}
        
        # We need a loop to run the async calls
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        for agent in agents:
            try:
                sharpe = loop.run_until_complete(
                    get_agent_sharpe(self.bot_id, agent, lookback_days=60)
                )
                sharpes[agent] = sharpe if sharpe is not None else 0.0
            except Exception as e:
                self._logger.warning(f"Could not get Sharpe for {agent}: {e}")
                sharpes[agent] = 0.0

        if not sharpes:
            return

        worst_agent = min(sharpes, key=sharpes.get)
        self._baseline_sharpe = sharpes[worst_agent]
        self._logger.info(
            f"Autoresearch: worst agent = {worst_agent} "
            f"(Sharpe={self._baseline_sharpe:.3f})"
        )

        # Step 2: Generate ONE targeted prompt modification
        current_prompt = load_agent_prompt(worst_agent)
        modification = self._generate_modification(worst_agent, current_prompt, sharpes)
        if not modification:
            self._logger.warning(f"Autoresearch: no modification generated for {worst_agent}")
            return

        # Step 3: Create git branch
        branch_name = (
            f"autoresearch/{worst_agent}-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        )
        try:
            subprocess.run(["git", "checkout", "-b", branch_name], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            self._logger.error(f"Git branch creation failed: {e.stderr.decode()}")
            return

        # Step 4: Write modified prompt
        try:
            self._write_modified_prompt(worst_agent, modification)
            subprocess.run(
                ["git", "add", f"backend/prompts/{worst_agent}_agent.md"],
                check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m",
                 f"autoresearch: {worst_agent} prompt modification\n\n{modification['rationale']}"],
                check=True, capture_output=True,
            )
        except Exception as e:
            self._logger.error(f"Prompt write/commit failed: {e}")
            subprocess.run(["git", "checkout", "main"], capture_output=True)
            return

        self._active_branch  = branch_name
        self._branch_agent   = worst_agent
        self._branch_start   = datetime.now(timezone.utc)
        self._logger.info(f"Autoresearch: branch {branch_name} created. Running for {EVALUATION_PERIOD_DAYS} trading days.")

    def _evaluation_complete(self) -> bool:
        if not self._branch_start:
            return False
        elapsed = (datetime.now(timezone.utc) - self._branch_start).days
        return elapsed >= EVALUATION_PERIOD_DAYS

    def _evaluate_and_decide(self):
        """Compare new Sharpe against baseline. Merge or revert."""
        from postgres_store import get_agent_sharpe
        import asyncio

        agent = self._branch_agent
        try:
            loop = asyncio.get_event_loop()
            new_sharpe = loop.run_until_complete(
                get_agent_sharpe(self.bot_id, agent, lookback_days=EVALUATION_PERIOD_DAYS)
            ) or 0.0
        except Exception:
            new_sharpe = 0.0

        improved = new_sharpe > self._baseline_sharpe

        self._logger.info(
            f"Autoresearch eval: {agent} | "
            f"baseline={self._baseline_sharpe:.3f} → new={new_sharpe:.3f} | "
            f"{'KEEP' if improved else 'REVERT'}"
        )

        if improved:
            # Merge into main
            try:
                subprocess.run(["git", "checkout", "main"], check=True, capture_output=True)
                subprocess.run(
                    ["git", "merge", "--no-ff", self._active_branch,
                     "-m", f"autoresearch: keep {agent} modification (Sharpe {self._baseline_sharpe:.3f}→{new_sharpe:.3f})"],
                    check=True, capture_output=True,
                )
                self._logger.info(f"Autoresearch: MERGED {self._active_branch}")
            except subprocess.CalledProcessError as e:
                self._logger.error(f"Merge failed: {e.stderr.decode()}")
        else:
            # Revert — delete branch, main retains original prompt
            try:
                subprocess.run(["git", "checkout", "main"], check=True, capture_output=True)
                subprocess.run(
                    ["git", "branch", "-D", self._active_branch],
                    check=True, capture_output=True,
                )
                self._logger.info(f"Autoresearch: REVERTED {self._active_branch}")
            except subprocess.CalledProcessError as e:
                self._logger.error(f"Branch delete failed: {e.stderr.decode()}")

        # Reset for next cycle
        self._active_branch  = None
        self._branch_agent   = None
        self._branch_start   = None
        self._baseline_sharpe = 0.0

    # ── Modification generation ──────────────────────────────────────

    def _generate_modification(
        self, agent_name: str, current_prompt: dict, all_sharpes: dict
    ) -> Optional[dict]:
        """Ask the LLM to produce ONE targeted improvement to the agent's prompt."""
        context = "\n".join(f"  {a}: Sharpe={s:.3f}" for a, s in all_sharpes.items())
        system = (
            "You are a prompt engineer specialising in financial AI agents. "
            "Your job is to improve a specific agent's prompt by making ONE targeted change. "
            "The change must be specific, testable, and address a plausible failure mode. "
            "Respond with only this JSON: "
            '{"modification": "<the new/changed text to insert or replace>", '
            '"location": "system|user", '
            '"rationale": "<one sentence explanation of what you changed and why>", '
            '"failure_mode": "<what failure pattern this addresses>"}'
        )
        prompt = (
            f"Agent: {agent_name}\n"
            f"Current rolling Sharpe (60d): {all_sharpes.get(agent_name, 0):.3f} (worst in panel)\n"
            f"All agent Sharpes for context:\n{context}\n\n"
            f"Current agent prompt:\n\n"
            f"SYSTEM:\n{current_prompt.get('system', '(not loaded)')}\n\n"
            f"USER TEMPLATE:\n{current_prompt.get('user_template', '(not loaded)')}\n\n"
            f"Generate ONE specific, targeted change to this prompt that could address "
            f"a plausible failure mode causing the poor Sharpe performance. "
            f"Limit the change to a single sentence or condition added to the prompt."
        )
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                max_tokens=400,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content
            import json
            import re
            try:
                return json.loads(raw)
            except Exception:
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if match:
                    return json.loads(match.group(0))
        except Exception as e:
            self._logger.error(f"Modification generation failed: {e}")
        return None

    def _write_modified_prompt(self, agent_name: str, modification: dict):
        """Apply the modification to the agent's prompt file."""
        path = os.path.join(
            os.path.dirname(__file__), "prompts", f"{agent_name}_agent.md"
        )
        if not os.path.exists(path):
            self._logger.warning(f"Prompt file not found: {path}")
            return

        with open(path) as f:
            content = f.read()

        location = modification.get("location", "user")
        new_text  = modification.get("modification", "")
        rationale = modification.get("rationale", "")

        section = "## System Prompt" if location == "system" else "## User Prompt Template"

        # Append the modification as a new condition at the end of the relevant section
        if section in content:
            # Find the section start
            section_idx = content.find(section)
            if section_idx != -1:
                # Find start of next section or end of file
                next_section_idx = content.find("\n## ", section_idx + len(section))
                if next_section_idx == -1:
                    # End of file
                    content += f"\n\n<!-- autoresearch: {rationale} -->\n{new_text}"
                else:
                    # Insert before next section
                    content = (
                        content[:next_section_idx]
                        + f"\n\n<!-- autoresearch: {rationale} -->\n{new_text}\n"
                        + content[next_section_idx:]
                    )

        with open(path, "w") as f:
            f.write(content)

        self._logger.info(f"Prompt file updated: {path}")
