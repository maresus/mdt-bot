"""
Unified Router for Health Center chatbot.
Single entry point for all intent classification.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict

from .confidence import (
    detect_intents,
    pick_primary_secondary,
    decide_action,
    SwitchAction,
    detect_service_type,
)
from app.services.clinic_config import get_clinic_config


class IntentType(str, Enum):
    BOOKING_APPOINTMENT = "BOOKING_APPOINTMENT"
    SERVICE_INFO = "SERVICE_INFO"
    PRICE = "PRICE"
    INFO = "INFO"
    UNSUPPORTED_SYMPTOM = "UNSUPPORTED_SYMPTOM"
    URGENCY = "URGENCY"
    GREETING = "GREETING"
    GOODBYE = "GOODBYE"
    AFFIRMATIVE = "AFFIRMATIVE"
    NEGATIVE = "NEGATIVE"
    GENERAL = "GENERAL"


@dataclass
class Decision:
    primary_intent: IntentType
    confidence: float
    action: SwitchAction
    secondary_intent: IntentType | None = None
    service_type: str | None = None
    resume_prompt: str | None = None


AFFIRMATIVE_WORDS = {
    "da", "ja", "ok", "okej", "okay", "seveda", "vredu", "lahko", "prosim", "grem", "gremo",
    "bom", "prišel", "prisla", "prsou", "pridem", "pridm", "yes", "yep", "sure", "cool",
    "tako", "je", "res", "v", "redu", "d", "a", "super", "odlično", "odlicno", "kul",
    "please",  # english
    "dada",
}

NEGATIVE_WORDS = {
    "ne", "nočem", "nochem", "pustimo", "rabim", "treba", "želim", "zelim", "raje", "rajši",
    "no", "nope", "hvala", "ni",
}


def _detect_affirmative_negative(message: str) -> IntentType | None:
    """Detect simple yes/no responses (word-based matching)."""
    text = message.lower().strip()
    # Remove extra spaces and punctuation
    text = " ".join(text.split())
    # Remove common punctuation
    for char in ".,!?":
        text = text.replace(char, "")

    words = text.split()
    if not words:
        return None

    # Check exact matches first (highest priority)
    if text in {"da", "ja", "ok", "okej", "okay", "ne", "yes", "no", "nope", "d a", "n e"}:
        if text in {"ne", "no", "nope", "n e"}:
            return IntentType.NEGATIVE
        return IntentType.AFFIRMATIVE

    # Check if ALL words are affirmative words
    if all(w in AFFIRMATIVE_WORDS for w in words):
        return IntentType.AFFIRMATIVE

    # Check if message starts with "ne" and rest are negative-compatible
    if words[0] == "ne" and all(w in NEGATIVE_WORDS or w in {"hvala", "bom"} for w in words):
        return IntentType.NEGATIVE

    return None


def route(message: str, unified_state: Dict[str, Any]) -> Decision:
    """
    Main routing function for health center chatbot.

    Args:
        message: User's message
        unified_state: Current conversation state

    Returns:
        Decision object with intent, confidence, and recommended action
    """
    # 1. Check for simple yes/no (exact match)
    affneg = _detect_affirmative_negative(message)
    if affneg:
        return Decision(
            primary_intent=affneg,
            confidence=1.0,
            action=SwitchAction.IGNORE,
        )

    context = unified_state.get("context", {}) if isinstance(unified_state, dict) else {}
    clinic_id = context.get("clinic_id") if isinstance(context, dict) else None
    clinic_config = get_clinic_config(clinic_id=clinic_id)
    service_map = clinic_config.get("service_map") if isinstance(clinic_config, dict) else None

    # 2. YAML-driven unsupported symptom guard (highest priority for symptom triage)
    unsupported_symptoms = []
    if isinstance(clinic_config, dict):
        unsupported_symptoms = clinic_config.get("unsupported_symptoms", []) or []
    if isinstance(unsupported_symptoms, dict):
        unsupported_symptoms = list(unsupported_symptoms.values())
    if isinstance(unsupported_symptoms, list) and unsupported_symptoms:
        lowered = message.lower()
        for entry in unsupported_symptoms:
            if not isinstance(entry, dict):
                continue
            keywords = entry.get("keywords", [])
            if isinstance(keywords, str):
                keywords = [keywords]
            if not isinstance(keywords, list):
                continue
            if any(str(kw).lower() in lowered for kw in keywords if kw):
                return Decision(
                    primary_intent=IntentType.UNSUPPORTED_SYMPTOM,
                    confidence=1.0,
                    action=SwitchAction.IGNORE,
                )

    # 3. Score all intents through unified system
    scores = detect_intents(message, service_map=service_map)
    primary, secondary, confidence = pick_primary_secondary(scores)
    primary_intent = IntentType(primary) if primary in IntentType._value2member_map_ else IntentType.GENERAL
    secondary_intent = (
        IntentType(secondary) if secondary in IntentType._value2member_map_ else None
    )

    # 3. Detect service type if applicable
    service_type = detect_service_type(message, service_map=service_map)

    # 4. Determine action based on current flow
    flow = unified_state.get("flow", "idle")
    action = SwitchAction.IGNORE

    if flow != "idle":
        # INFO/PRICE/SERVICE_INFO during flow = soft interrupt (answer + continue)
        if primary_intent in {IntentType.INFO, IntentType.PRICE, IntentType.SERVICE_INFO}:
            action = SwitchAction.SOFT_INTERRUPT
        # URGENCY always gets priority
        elif primary_intent == IntentType.URGENCY:
            action = SwitchAction.HARD_SWITCH
        else:
            action = decide_action(confidence)

    return Decision(
        primary_intent=primary_intent,
        secondary_intent=secondary_intent,
        confidence=confidence,
        action=action,
        service_type=service_type,
    )


class InterruptManager:
    @staticmethod
    def should_interrupt(decision: Decision) -> bool:
        return decision.action == SwitchAction.SOFT_INTERRUPT


def format_interrupt_response(answer: str, resume: str | None) -> str:
    """Format response with optional resume prompt."""
    if resume:
        return f"{answer}\n\n---\n\n{resume}"
    return answer
