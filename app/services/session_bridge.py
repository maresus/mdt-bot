from __future__ import annotations

from typing import Optional

from app.services.session.unified_state import FlowStep, get_unified_state


def blank_appointment_state() -> dict[str, Optional[str | int]]:
    return {
        "step": None,
        "service_type": None,
        "date": None,
        "time": None,
        "name": None,
        "phone": None,
        "email": None,
        "reason": None,
        "patient_age": None,
        "patient_health_card": None,
        "note": None,
        "waiting_resume_confirmation": False,
        "awaiting_booking_confirmation": False,
    }


appointment_states: dict[str, dict[str, Optional[str | int]]] = {}


def get_appointment_state(session_id: str) -> dict[str, Optional[str | int]]:
    """Get or create legacy appointment state for session."""
    if session_id not in appointment_states:
        appointment_states[session_id] = blank_appointment_state()

    state = appointment_states[session_id]

    # Hydrate legacy state from unified (Redis-backed) state after cold start.
    if not any(
        state.get(k)
        for k in ("step", "service_type", "date", "time", "name", "phone", "email", "reason")
    ):
        unified = get_unified_state(session_id)
        appt = dict(unified.get("appointment_data") or {})
        unified_step = unified.get("step")

        if any(appt.get(k) for k in ("service_type", "date", "time", "name", "phone", "email", "reason")) or unified_step:
            step = "select_service" if unified_step == FlowStep.SERVICE.value else unified_step
            state["step"] = step
            state["service_type"] = appt.get("service_type")
            state["date"] = appt.get("date")
            state["time"] = appt.get("time")
            state["name"] = appt.get("name")
            state["phone"] = appt.get("phone")
            state["email"] = appt.get("email")
            state["reason"] = appt.get("reason")

    return state


def reset_appointment_state(state: dict[str, Optional[str | int]]) -> None:
    state.update(blank_appointment_state())

