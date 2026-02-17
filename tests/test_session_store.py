from app.services.session.store import InMemorySessionStore
from app.services.session.unified_state import get_unified_state, reset_unified_state


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
