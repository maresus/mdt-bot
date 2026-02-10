"""Policy module for handling interrupts during booking flow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from app.services.routing.unified_router import IntentType


@dataclass
class BookingInterruptDeps:
    is_in_flow: Callable[[str], bool]
    get_current_step: Callable[[str], str | None]
    get_appointment_data: Callable[[str], dict[str, Any]]
    get_context_value: Callable[[str, str, Any], Any]
    set_context_value: Callable[[str, str, Any], None]
    extract_date_from_message: Callable[[str], Optional[str]]
    extract_time_from_message: Callable[[str], Optional[str]]
    extract_service_type: Callable[[str], Optional[str]]
    is_likely_full_name: Callable[[str], bool]
    build_interrupt_response: Callable[[str, str | None, bool], str]
    build_resume_prompt: Callable[[str | None, dict[str, Any]], str]
    interrupt_answer: Callable[..., Optional[str]]
    get_info_response: Callable[[str], str]
    get_service_info: Callable[[str], Optional[dict[str, Any]]]
    looks_like_symptom_report: Callable[[str], bool]


SYMPTOM_KEY_BY_SERVICE = {
    "ortoped": "ortopedija",
    "dermatolog": "dermatologija",
    "okulist": "oftalmologija",
}


def handle_booking_interrupt(
    *,
    message: str,
    session_id: str,
    decision_intent: IntentType,
    service_hint: str | None,
    deps: BookingInterruptDeps,
) -> str | None:
    """Apply booking interrupt policy. Return response text or None to continue."""
    if not deps.is_in_flow(session_id):
        return None

    step = deps.get_current_step(session_id)
    appointment_data = deps.get_appointment_data(session_id)
    state_view = {"step": step, **appointment_data}

    # If user is answering expected step, continue booking flow.
    if step == "date" and deps.extract_date_from_message(message):
        return None
    if step == "time" and deps.extract_time_from_message(message):
        return None
    if step in {"service", "select_service", None} and not appointment_data.get("service_type"):
        if deps.extract_service_type(message):
            return None
    if step == "name" and deps.is_likely_full_name(message):
        return None
    if step == "phone":
        cleaned = "".join(ch for ch in message if ch.isdigit() or ch == "+")
        if len(cleaned) >= 8:
            return None
    if step == "email" and ("@" in message and "." in message.split("@")[-1]):
        return None
    if step == "reason" and message.strip():
        return None

    current_service = appointment_data.get("service_type")
    incoming_service = (service_hint or "").lower() if service_hint else None

    # If user asks service info with a different service while booking, require explicit switch.
    if decision_intent == IntentType.SERVICE_INFO and incoming_service and current_service:
        if incoming_service != str(current_service).lower():
            info = deps.get_service_info(incoming_service)
            label = info["name"] if info else incoming_service
            current_info = deps.get_service_info(str(current_service).lower())
            current_label = current_info["name"] if current_info else str(current_service)
            deps.set_context_value(session_id, "pending_service_switch", incoming_service)
            return (
                f"Glede na opis priporočam **{label}**.\n\n"
                f"Trenutno imate izbran **{current_label}**.\n"
                f"Želite preklopiti na **{label}**? (DA / NE)"
            )

    # Soft-interrupt for info/price/service info
    if decision_intent in {IntentType.INFO, IntentType.PRICE, IntentType.SERVICE_INFO}:
        answer = deps.interrupt_answer(
            message=message,
            primary_intent=decision_intent,
            service_hint=service_hint,
            active_service=current_service,
        )
        if answer:
            return deps.build_interrupt_response(answer, step, True)

    # Symptom during booking -> short advice + resume booking
    if deps.looks_like_symptom_report(message):
        mapped = SYMPTOM_KEY_BY_SERVICE.get(str(current_service).lower()) if current_service else None
        if mapped:
            answer = deps.get_info_response(mapped)
        else:
            answer = deps.get_info_response("storitve")
        return deps.build_interrupt_response(answer, step, True)

    # Otherwise, repeat the expected step prompt.
    return deps.build_resume_prompt(step, state_view)
