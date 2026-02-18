from contextvars import copy_context
from copy import deepcopy

from app.services.clinic_config import reset_current_clinic_id, set_current_clinic_id
from app.services.session.store import InMemorySessionStore
from app.services.session import unified_state
from app.services.session.unified_state import StateManager, get_unified_state, reset_unified_state
from app.services.triage_service import get_triage_service


def test_in_memory_store_roundtrip() -> None:
    store = InMemorySessionStore()
    key = "test::session::1"
    value = {"flow": "idle"}

    assert store.get(key) is None
    store.set(key, value)
    assert store.get(key) == value
    store.delete(key)
    assert store.get(key) is None


def test_unified_state_reset_clears_step() -> None:
    session_id = "test::unified::state::1"
    state = get_unified_state(session_id)
    state["flow"] = "appointment"
    state["step"] = "date"

    reset_unified_state(session_id)
    state_after = get_unified_state(session_id)

    assert state_after["flow"] == "idle"
    assert state_after["step"] is None


def test_triage_session_roundtrip_in_store() -> None:
    session_id = "test::triage::1"
    triage = get_triage_service()

    started = triage.start_triage_session(session_id)
    assert started["session_id"] == session_id

    loaded = triage.get_session(session_id)
    assert loaded is not None
    assert loaded.session_id == session_id

    assert triage.end_session(session_id) is True
    assert triage.get_session(session_id) is None


def test_reset_current_clinic_id_tolerates_foreign_context_token() -> None:
    token_box: dict[str, object] = {}

    def _set_in_other_context() -> None:
        token_box["token"] = set_current_clinic_id("other-context")

    ctx = copy_context()
    ctx.run(_set_in_other_context)
    token = token_box["token"]

    # Must not raise even when token was created in a different context.
    reset_current_clinic_id(token)


def test_state_manager_persists_with_copying_store(monkeypatch) -> None:
    class CopyingStore:
        def __init__(self) -> None:
            self._data = {}

        def get(self, key):
            value = self._data.get(key)
            return deepcopy(value) if value is not None else None

        def set(self, key, value) -> None:
            self._data[key] = deepcopy(value)

        def delete(self, key) -> None:
            self._data.pop(key, None)

    store = CopyingStore()
    monkeypatch.setattr(unified_state, "get_session_store", lambda: store)

    sid = "test::copying-store::state"
    mgr = StateManager(sid)
    mgr.set_context_value("suggested_service", "DERMATOLOG")
    assert StateManager(sid).get_context_value("suggested_service") == "DERMATOLOG"

    legacy_state = {}
    mgr.transition_to_booking(service_type="DERMATOLOG", legacy_state=legacy_state)
    assert unified_state.is_in_flow(sid) is True
    assert unified_state.get_current_step(sid) == "date"
    assert unified_state.get_appointment_data(sid).get("service_type") == "DERMATOLOG"

    StateManager(sid).set_appointment_field("date", "15.03.2026")
    assert StateManager(sid).get_appointment_data().get("date") == "15.03.2026"
