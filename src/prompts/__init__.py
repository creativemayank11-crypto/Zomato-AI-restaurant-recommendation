"""Prompt templates and serialization utilities for the cognitive recommendation layer."""
from src.prompts.templates import (
    SYSTEM_PROMPT,
    serialize_candidates_for_prompt,
    sanitize_user_notes,
    build_user_prompt,
)

__all__ = [
    "SYSTEM_PROMPT",
    "serialize_candidates_for_prompt",
    "sanitize_user_notes",
    "build_user_prompt",
]
