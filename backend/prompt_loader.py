import os
import logging

logger = logging.getLogger("tradeclaw.prompt_loader")

_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

def load_agent_prompt(agent_name: str) -> dict:
    """
    Load system and user prompt template from prompts/<agent_name>_agent.md.
    Returns {"system": str, "user_template": str}.
    """
    path = os.path.join(_PROMPTS_DIR, f"{agent_name}_agent.md")
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            content = f.read()
        
        # Split on the section headers
        system = ""
        user_tpl = ""
        
        if "## System Prompt" in content:
            parts = content.split("## System Prompt", 1)[1]
            if "## User Prompt Template" in parts:
                system_raw, user_raw = parts.split("## User Prompt Template", 1)
                system   = system_raw.strip()
                user_tpl = user_raw.strip()
            else:
                system = parts.strip()
        
        return {"system": system, "user_template": user_tpl}
    except Exception as e:
        logger.error(f"Error loading prompt {agent_name}: {e}")
        return {}

class PromptLoader:
    """Legacy class wrapper for compatibility if needed."""
    @staticmethod
    def get_agent_prompts(agent_name: str) -> tuple[str, str]:
        p = load_agent_prompt(agent_name)
        return p.get("system", ""), p.get("user_template", "")
