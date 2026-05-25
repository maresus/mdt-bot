"""
Direct LLM chat for MDT&T — Kovačnik V2 architecture.
One LLM call handles all info queries; booking = widget form.
"""
from __future__ import annotations

import os
from pathlib import Path
from openai import OpenAI

from app.rag.rag_engine import rag_engine


_SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "clinics" / "mdt" / "system_prompt.txt"
)
_DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1").strip()


def _load_system_prompt() -> str:
    if _SYSTEM_PROMPT_PATH.exists():
        return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
    return "Si digitalni asistent MDT&T diagnostičnega centra v Mariboru."


def _rag_context(message: str) -> str:
    try:
        results = rag_engine.search(message, top_k=3)
        parts = [item.content.strip() for item in results if item.content.strip()]
        return "\n\n".join(parts)
    except Exception:
        return ""


def chat(
    message: str,
    history: list[dict[str, str]] | None = None,
    client: OpenAI | None = None,
    model: str | None = None,
) -> dict[str, str]:
    """Main chat function for MDT&T. Returns {"reply": "..."}."""
    if model is None:
        model = _DEFAULT_MODEL
    if client is None:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    system_prompt = _load_system_prompt()

    context = _rag_context(message)
    if context:
        system_prompt += f"\n\n## Dodatni kontekst iz baze znanja:\n{context}"

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": message})

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=400,
    )

    reply = (response.choices[0].message.content or "").strip()
    if not reply:
        reply = "Oprostite, nisem razumel vprašanja. Pokličite nas: 02 23 53 552."

    return {"reply": reply}
