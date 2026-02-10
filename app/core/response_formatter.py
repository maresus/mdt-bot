"""Response formatting utilities (contract v0.2)."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict

from app.services.clinic_config import get_clinic_config
from app.services.health_center_extensions import get_available_time_slots
from app.services.session.unified_state import FlowStep, FlowType, StateManager


ResponsePayload = Dict[str, Any]


def _build_ui_payload(state_manager: StateManager | None) -> dict[str, Any] | None:
    if state_manager is None:
        return None

    state = state_manager.get_state()
    ui_override = state_manager.get_context_value("ui_override", None)
    if isinstance(ui_override, dict):
        return ui_override
    step = state.get("step")
    flow = state.get("flow")
    appointment = state.get("appointment_data", {})
    clinic_id = state_manager.get_context_value("clinic_id", None)
    config = get_clinic_config(clinic_id=clinic_id)

    if flow == FlowType.APPOINTMENT.value and step in (None, FlowStep.SERVICE.value, "select_service"):
        services = config.get("services", {}) or {}
        options = []
        for key, payload in services.items():
            label = payload.get("name") if isinstance(payload, dict) else str(payload)
            label = label or str(key)
            options.append({"label": label, "value": label})
        if options:
            return {
                "type": "service_select",
                "label": "Izberite storitev",
                "options": options,
            }

    if step == FlowStep.DATE.value:
        return {
            "type": "date_picker",
            "label": "Izberite datum",
            "min_date": date.today().isoformat(),
        }

    if step == FlowStep.TIME.value:
        date_str = str(appointment.get("date") or "")
        service_type = str(appointment.get("service_type") or "")
        slots: list[str] = []
        if date_str and service_type:
            try:
                slots = get_available_time_slots(date_str, service_type.lower(), clinic_id=clinic_id)
            except Exception:
                slots = []
        if slots:
            return {
                "type": "time_slots",
                "label": f"Prosti termini za {date_str}",
                "slots": slots[:12],
            }

    if step == FlowStep.CONFIRM.value:
        return {
            "type": "confirm",
            "label": "Ali so podatki pravilni?",
            "options": ["DA", "NE"],
        }

    return None


def format_response(
    text: str,
    state_manager: StateManager | None = None,
    metadata: dict[str, Any] | None = None,
) -> ResponsePayload:
    """Return contract v0.2 payload (always JSON)."""
    meta = dict(metadata or {})
    if state_manager is not None:
        state = state_manager.get_state()
        meta.setdefault("flow", state.get("flow"))
        meta.setdefault("step", state.get("step"))
        clinic_id = state_manager.get_context_value("clinic_id", None)
        meta.setdefault("clinic_id", get_clinic_config(clinic_id=clinic_id).get("clinic_id", "default"))

    ui_payload = meta.pop("ui", None)
    if ui_payload is None:
        ui_payload = _build_ui_payload(state_manager)
    if ui_payload is not None:
        meta.setdefault("ui", ui_payload)
    payload: ResponsePayload = {
        "text": text,
        "metadata": meta,
        "ui": ui_payload,
    }
    return payload


def with_resume(
    answer: str,
    resume_prompt: str | None = None,
    state_manager: StateManager | None = None,
    metadata: dict[str, Any] | None = None,
) -> ResponsePayload:
    """Compose interrupt answer with optional resume section."""
    if resume_prompt:
        text = f"{answer}\n\n---\n\n{resume_prompt}"
    else:
        text = answer
    return format_response(text, state_manager=state_manager, metadata=metadata)
