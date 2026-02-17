from app.services.session.store import InMemorySessionStore
from app.services.session.unified_state import get_unified_state, reset_unified_state
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
