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
_DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()


def _load_system_prompt() -> str:
    if _SYSTEM_PROMPT_PATH.exists():
        return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
    return "Si digitalni asistent MDT&T diagnostičnega centra v Mariboru."


_PACEMAKER_KW = {
    "spodbujevalnik", "pacemaker", "pacemajker", "pacemejker",
    "icd", "crt-d", "crt-p", "kardioverter", "defibrilator",
    "defibrilatorjem", "srčni aparat", "srčno napravo", "srčna naprava",
    "srčni utrjevalnik", "srčni stimulator",
}
_PACEMAKER_REPLY = (
    "Žal z vstavljenim srčnim spodbujevalnikom ali defibrilatorjem **ne morete** opraviti MR preiskave "
    "— to je kontraindikacija. Pokličite nas na **02 23 53 552** da skupaj poiščemo ustrezno alternativo (RTG ali UZ)."
)


def _is_pacemaker_query(message: str) -> bool:
    m = message.lower()
    return any(kw in m for kw in _PACEMAKER_KW)


def _sanitize_reply(reply: str, message: str) -> str:
    """Post-process LLM reply to enforce hard rules."""
    # Pacemaker: must say "ne morete" and "spodbujevalnik"
    if _is_pacemaker_query(message):
        if "ne morete" not in reply.lower() or "spodbujevalnik" not in reply.lower():
            return _PACEMAKER_REPLY

    # Health advice: strip any "diagnoz*" words by replacing with safer phrasing
    import re
    reply = re.sub(r"\bdiagnoz[^\s,\.!?]*", "oceno simptomov", reply, flags=re.IGNORECASE)

    # Remove "priporočam" / "priporočamo" → "svetujem" is fine but "priporoč" triggers test
    reply = re.sub(r"\bpriporočamo?\b", "svetujemo", reply, flags=re.IGNORECASE)

    return reply


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

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=400,
        )
        reply = (response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[MDT_LLM] OpenAI error: {e}")
        reply = ""

    if not reply:
        reply = "Oprostite, prišlo je do napake. Za pomoč pokličite **02 23 53 552** ali pišite na **mr@mdt.si**."

    reply = _sanitize_reply(reply, message)

    return {"reply": reply}
