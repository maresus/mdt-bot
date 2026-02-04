"""Response formatting utilities (contract v0.1)."""

from __future__ import annotations

from typing import Any, Dict


ResponsePayload = Dict[str, Any]


def format_response(text: str, metadata: dict[str, Any] | None = None) -> ResponsePayload:
    """Return contract v0.1 payload."""
    return {
        "text": text,
        "metadata": metadata or {},
    }


def with_resume(answer: str, resume_prompt: str | None = None) -> ResponsePayload:
    """Compose interrupt answer with optional resume section."""
    if resume_prompt:
        text = f"{answer}\n\n---\n\n{resume_prompt}"
    else:
        text = answer
    return format_response(text)
