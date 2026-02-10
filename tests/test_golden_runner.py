import json
from pathlib import Path

import pytest

from app.core.response_formatter import format_response
from app.services.chat_router import (
    get_appointment_state,
    handle_unified_routing,
    reset_appointment_state,
)
from app.services.routing.unified_router import route as unified_route
from app.services.session.unified_state import FlowStep, FlowType, StateManager, reset_unified_state


GOLDEN_PATH = Path(__file__).resolve().parent / "golden_intents.json"


def _normalize_intent(value: str) -> str:
    if value.upper() == "BOOKING":
        return "BOOKING_APPOINTMENT"
    return value.upper()


def _normalize_service(value: str | None) -> str | None:
    if value is None:
        return None
    return value.upper()


@pytest.mark.parametrize("case", json.loads(GOLDEN_PATH.read_text(encoding="utf-8")))
def test_golden_cases(case):
    message = case["input"]
    expected = case.get("expected", {})
    session_id = f"golden-{hash(message) & 0xFFFF}"
    clinic_id = case.get("clinic_id", "lj_center")

    reset_unified_state(session_id)
    legacy_state = get_appointment_state(session_id)
    reset_appointment_state(legacy_state)

    pre_state = case.get("pre_state") or {}
    if pre_state:
        state_mgr = StateManager(session_id)
        state_mgr.set_context_value("clinic_id", clinic_id)
        if "flow" in pre_state:
            try:
                state_mgr.set_flow(FlowType(pre_state["flow"]))
            except Exception:
                pass
        if "step" in pre_state:
            try:
                state_mgr.set_step(FlowStep(pre_state["step"]))
            except Exception:
                state_mgr.set_step(None)
        for field, value in (pre_state.get("appointment_data") or {}).items():
            state_mgr.set_appointment_field(field, value)
    else:
        StateManager(session_id).set_context_value("clinic_id", clinic_id)

    response_text = handle_unified_routing(message, session_id, clinic_id=clinic_id) or ""
    decision = unified_route(message, StateManager(session_id).get_state())

    expected_intent = _normalize_intent(expected.get("intent", ""))
    if expected_intent:
        assert decision.primary_intent.value == expected_intent

    expected_service = _normalize_service(expected.get("service"))
    if expected_service is not None:
        assert _normalize_service(decision.service_type) == expected_service

    if "ui_type" in expected:
        payload = format_response(response_text, state_manager=StateManager(session_id), metadata={})
        ui_type = payload.get("ui", {})["type"] if payload.get("ui") else None
        assert ui_type == expected.get("ui_type")
