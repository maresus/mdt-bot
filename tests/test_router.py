"""
Unit tests for unified routing (v0.3).
Run with: venv/bin/pytest tests/test_router.py -v
"""

from app.services.routing.unified_router import route as unified_route, IntentType
from app.services.session.unified_state import get_unified_state, reset_unified_state, StateManager
from app.services.clinic_config import set_current_clinic_id


def _route(message: str, session_id: str = "test_session", clinic_id: str = "lj_center"):
    reset_unified_state(session_id)
    set_current_clinic_id(clinic_id)
    state_mgr = StateManager(session_id)
    state_mgr.set_context_value("clinic_id", clinic_id)
    state = get_unified_state(session_id)
    return unified_route(message, state)


def test_booking_with_service():
    decision = _route("Rad bi se naročil pri ortopedu")
    assert decision.primary_intent == IntentType.BOOKING_APPOINTMENT
    assert decision.service_type == "ORTOPED"


def test_booking_without_service():
    decision = _route("Rad bi se naročil")
    assert decision.primary_intent == IntentType.BOOKING_APPOINTMENT
    assert decision.service_type is None


def test_info_hours():
    decision = _route("Kdaj ste odprti?")
    assert decision.primary_intent == IntentType.INFO


def test_price_service():
    decision = _route("Koliko stane ortoped?")
    assert decision.primary_intent == IntentType.PRICE
    assert decision.service_type == "ORTOPED"


def test_greeting():
    decision = _route("Pozdravljeni")
    assert decision.primary_intent == IntentType.GREETING


def test_symptom_service_info():
    decision = _route("Imam izpuščaj na koži")
    assert decision.primary_intent == IntentType.SERVICE_INFO
    assert decision.service_type == "DERMATOLOG"


def test_urgency():
    decision = _route("Nujno potrebujem pomoč")
    assert decision.primary_intent == IntentType.URGENCY
