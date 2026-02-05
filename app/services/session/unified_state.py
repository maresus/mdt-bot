"""
Unified State Management for Health Center chatbot.
Handles appointment booking flows with interrupt support.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional


class FlowType(str, Enum):
    IDLE = "idle"
    APPOINTMENT = "appointment"  # Booking an appointment


class FlowStep(str, Enum):
    # Appointment flow steps
    SERVICE = "service"       # Which service (dermatolog, ortoped, etc.)
    DATE = "date"             # Preferred date
    TIME = "time"             # Preferred time
    NAME = "name"             # Patient name
    PHONE = "phone"           # Contact phone
    EMAIL = "email"           # Contact email (optional)
    REASON = "reason"         # Visit reason
    CONFIRM = "confirm"       # Confirmation


# In-memory state storage (per session_id)
unified_states: Dict[str, Dict[str, Any]] = {}


class StateManager:
    """Single writer for unified state."""

    def __init__(self, session_id: str):
        self.session_id = session_id

    def get_state(self) -> Dict[str, Any]:
        return get_unified_state(self.session_id)

    def reset_all(self) -> None:
        reset_unified_state(self.session_id)

    def reset_flow_only(self) -> None:
        reset_flow(self.session_id)

    def ensure_context(self) -> Dict[str, Any]:
        state = self.get_state()
        return state.setdefault("context", {})

    def set_flow(self, flow_type: FlowType) -> None:
        state = self.get_state()
        state["flow"] = flow_type.value
        self._log_change(f"flow={flow_type.value}")

    def set_step(self, step: Optional[FlowStep]) -> None:
        state = self.get_state()
        state["step"] = step.value if step else None
        self._log_change(f"step={state['step']}")

    def start_flow(self, flow_type: FlowType, initial_step: FlowStep) -> None:
        state = self.get_state()
        state["flow"] = flow_type.value
        state["step"] = initial_step.value
        self._log_change(f"start_flow={flow_type.value}:{initial_step.value}")

    def advance_step(self, next_step: FlowStep) -> None:
        state = self.get_state()
        state["step"] = next_step.value
        self._log_change(f"advance_step={next_step.value}")

    def set_context_value(self, key: str, value: Any) -> None:
        ctx = self.ensure_context()
        ctx[key] = value
        self._log_change(f"context[{key}]={value}")

    def get_context_value(self, key: str, default: Any = None) -> Any:
        return self.ensure_context().get(key, default)

    def clear_context_key(self, key: str) -> None:
        ctx = self.ensure_context()
        if key in ctx:
            del ctx[key]
            self._log_change(f"context[{key}]=<cleared>")

    def get_appointment_data(self) -> Dict[str, Any]:
        return self.get_state()["appointment_data"]

    def set_appointment_field(self, field: str, value: Any) -> None:
        state = self.get_state()
        if field in state["appointment_data"]:
            state["appointment_data"][field] = value
            self._log_change(f"appointment[{field}]={value}")

    def clear_appointment_data(self) -> None:
        state = self.get_state()
        state["appointment_data"] = blank_unified_state()["appointment_data"]
        self._log_change("appointment=<cleared>")

    def get_full_state(self) -> Dict[str, Any]:
        import copy
        return copy.deepcopy(self.get_state())

    def _log_change(self, message: str) -> None:
        state = self.get_state()
        history = state.setdefault("history", [])
        history.append(message)


def blank_unified_state() -> Dict[str, Any]:
    """Create a fresh unified state."""
    return {
        "flow": FlowType.IDLE.value,
        "step": None,
        "appointment_data": {
            "service_type": None,
            "date": None,
            "time": None,
            "name": None,
            "phone": None,
            "email": None,
            "reason": None,
        },
        "interrupt_stack": [],
        "context": {},
        "history": [],
    }


def get_unified_state(session_id: str) -> Dict[str, Any]:
    """Get or create unified state for session."""
    if session_id not in unified_states:
        unified_states[session_id] = blank_unified_state()
    return unified_states[session_id]


def reset_unified_state(session_id: str) -> None:
    """Reset state to blank."""
    unified_states[session_id] = blank_unified_state()


def reset_flow(session_id: str) -> None:
    """Reset only the flow, keeping context."""
    state = get_unified_state(session_id)
    state["flow"] = FlowType.IDLE.value
    state["step"] = None
    state["appointment_data"] = blank_unified_state()["appointment_data"]
    state["interrupt_stack"] = []


def is_in_flow(session_id: str) -> bool:
    """Check if session is in an active flow."""
    state = get_unified_state(session_id)
    return state["flow"] != FlowType.IDLE.value


def get_current_flow(session_id: str) -> str:
    """Get current flow type."""
    return get_unified_state(session_id)["flow"]


def get_current_step(session_id: str) -> str | None:
    """Get current step in flow."""
    return get_unified_state(session_id)["step"]


def start_flow(session_id: str, flow_type: FlowType, initial_step: FlowStep) -> None:
    """Start a new flow."""
    StateManager(session_id).start_flow(flow_type, initial_step)


def advance_step(session_id: str, next_step: FlowStep) -> None:
    """Advance to next step in flow."""
    StateManager(session_id).advance_step(next_step)


def push_interrupt(session_id: str, intent: str, data: Dict[str, Any] | None = None) -> None:
    """Push an interrupt to the stack (for nested flows)."""
    state = get_unified_state(session_id)
    state["interrupt_stack"].append({
        "intent": intent,
        "data": data or {},
        "previous_step": state["step"],
    })


def pop_interrupt(session_id: str) -> Dict[str, Any] | None:
    """Pop and return the last interrupt."""
    state = get_unified_state(session_id)
    if state["interrupt_stack"]:
        return state["interrupt_stack"].pop()
    return None


def get_appointment_data(session_id: str) -> Dict[str, Any]:
    """Get appointment data for session."""
    return get_unified_state(session_id)["appointment_data"]


def set_appointment_field(session_id: str, field: str, value: Any) -> None:
    """Set a field in appointment data."""
    StateManager(session_id).set_appointment_field(field, value)


def get_missing_appointment_fields(session_id: str) -> List[str]:
    """Get list of missing required fields."""
    data = get_appointment_data(session_id)
    required = ["service_type", "date", "time", "name", "phone"]
    return [f for f in required if not data.get(f)]


def is_appointment_complete(session_id: str) -> bool:
    """Check if all required appointment fields are filled."""
    return len(get_missing_appointment_fields(session_id)) == 0
