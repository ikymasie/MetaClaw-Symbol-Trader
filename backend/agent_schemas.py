"""
TradeClaw — Sub-Agent LLM Response Schemas
==========================================
Shared Pydantic models for structured outputs from sub-agents.

These schemas serve two purposes:
  1. Strict validation of LLM responses (post-hoc, via `_extract_json` → model validation).
  2. JSON-Schema binding for the Gemini OpenAI-compatible endpoint via
     `response_format={"type": "json_schema", "json_schema": {...}}` so the
     model is forced to emit conforming output (Phase 2, §6.2).

When tightening the contract here, also update prompts in `backend/prompts/`
so the LLM is told what the schema looks like.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Allowed directional vote values. Kept as a module-level constant so callers
# (e.g. SubAgentPool.deliberate) can reference the same canonical set without
# string drift.
VoteLiteral = Literal["BUY", "SELL", "HOLD", "VETO"]
ALLOWED_VOTES: tuple[str, ...] = ("BUY", "SELL", "HOLD", "VETO")


class AgentSignalSchema(BaseModel):
    """Structured output from a sub-agent analysis run."""

    # Allow trailing whitespace / unknown keys to be ignored — LLMs are noisy.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    sentiment: float = Field(
        description="Sentiment score from -1.0 (very bearish) to +1.0 (very bullish).",
        ge=-1.0,
        le=1.0,
    )
    confidence: float = Field(
        description="Confidence in the analysis from 0.0 to 1.0.",
        ge=0.0,
        le=1.0,
    )
    reasoning: str = Field(
        description="Concise natural language reasoning for the signal (2-3 sentences).",
        min_length=1,
        max_length=2000,
    )
    sources: List[str] = Field(
        default_factory=list,
        description="List of URLs or data sources used for the analysis.",
        max_length=20,
    )


class AgentVoteSchema(BaseModel):
    """Structured directional vote from a sub-agent during deliberation."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    vote: VoteLiteral = Field(
        description="Directional vote. Must be exactly one of: BUY, SELL, HOLD, VETO."
    )
    confidence: float = Field(
        description="Confidence in the vote from 0.0 to 1.0.",
        ge=0.0,
        le=1.0,
    )
    reasoning: str = Field(
        description="Explanation for the vote direction or veto reason.",
        min_length=1,
        max_length=2000,
    )
    veto_reason: Optional[str] = Field(
        default=None,
        description="Specific reason for a VETO, if applicable.",
        max_length=500,
    )


class CROObjectionSchema(BaseModel):
    """Structured output from CRO agent adversarial review."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    objection: str = Field(
        description="One sentence reason not to take the trade, or empty string if none.",
        max_length=500,
    )
    severity: float = Field(
        description="Severity of the objection from 0.0 to 1.0.",
        ge=0.0,
        le=1.0,
    )
    confidence: float = Field(
        description="Confidence in the objection from 0.0 to 1.0.",
        ge=0.0,
        le=1.0,
    )


def to_gemini_response_format(model_cls: type[BaseModel], name: Optional[str] = None) -> dict:
    """
    Build a Gemini OpenAI-compatible `response_format` payload binding a
    Pydantic model to the chat-completion call.

    Per Google's OpenAI-compat docs (generativelanguage.googleapis.com), Gemini
    supports `response_format={"type": "json_schema", "json_schema": {...}}`,
    forcing the model to emit JSON matching the supplied JSON Schema.

    On unsupported clients/models the caller should fall back to plain
    `{"type": "json_object"}`.
    """
    schema = model_cls.model_json_schema()
    # Gemini's JSON-schema dialect doesn't accept some Pydantic-emitted fields
    # like `additionalProperties` defaults; strip aggressively.
    schema = _strip_unsupported_schema_keys(schema)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name or model_cls.__name__,
            "schema": schema,
            "strict": True,
        },
    }


def _strip_unsupported_schema_keys(node):
    """
    Recursively remove keys not supported by Gemini's JSON-Schema dialect.

    Gemini rejects: `$defs`, `$ref` (it inlines), `additionalProperties: true`,
    `title` on nested objects, and certain `format` strings. This is a
    conservative pass that removes the most common offenders.
    """
    BLOCKED_KEYS = {"$defs", "$ref", "additionalProperties", "title"}
    if isinstance(node, dict):
        cleaned = {}
        for k, v in node.items():
            if k in BLOCKED_KEYS:
                continue
            cleaned[k] = _strip_unsupported_schema_keys(v)
        return cleaned
    if isinstance(node, list):
        return [_strip_unsupported_schema_keys(x) for x in node]
    return node
