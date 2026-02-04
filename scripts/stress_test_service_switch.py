#!/usr/bin/env python3
"""
5 stress scenarijev za preklop storitve med aktivnim booking flow-om.

Zaženi z:
    source .venv/bin/activate
    python scripts/stress_test_service_switch.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.chat_router import (  # type: ignore
    handle_unified_routing,
    get_appointment_state,
)
from app.services.session.unified_state import (
    get_unified_state,
    reset_unified_state,
    start_flow,
    FlowType,
    FlowStep,
)


def reset_session(session_id: str, service: str = "dermatolog"):
    reset_unified_state(session_id)
    state = get_appointment_state(session_id)
    state["service_type"] = service
    state["step"] = "date"
    start_flow(session_id, FlowType.APPOINTMENT, FlowStep.DATE)
    return state


def check(name: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    print(f"{status} | {name}")
    if not condition and detail:
        print(f"       {detail}")
    return condition


def main() -> int:
    passed = 0
    failed = 0

    # 1) Soft interrupt info during booking should answer + resume
    sid = "stress-1"
    reset_session(sid, "ortoped")
    resp = handle_unified_routing("imate parking?", sid) or ""
    if check("1. Booking + parking interrupt", "Parkiranje" in resp and "Nadaljujemo" in resp):
        passed += 1
    else:
        failed += 1

    # 2) Symptom for different service should ask switch confirmation
    sid = "stress-2"
    reset_session(sid, "dermatolog")
    resp = handle_unified_routing("boli me koleno", sid) or ""
    if check("2. Predlagan preklop storitve", "Želite preklopiti" in resp and "Ortoped" in resp):
        passed += 1
    else:
        failed += 1

    # 3) Confirm switch with DA
    sid = "stress-3"
    state = reset_session(sid, "dermatolog")
    _ = handle_unified_routing("boli me koleno", sid)
    resp = handle_unified_routing("da", sid) or ""
    switched = state.get("service_type") == "ortoped"
    if check("3. DA preklopi na ortoped", switched and "Kateri datum" in resp):
        passed += 1
    else:
        failed += 1

    # 4) Reject switch with NE
    sid = "stress-4"
    state = reset_session(sid, "dermatolog")
    _ = handle_unified_routing("boli me koleno", sid)
    resp = handle_unified_routing("ne", sid) or ""
    kept = state.get("service_type") == "dermatolog"
    if check("4. NE ohrani obstoječo storitev", kept and "Nadaljujemo z naročilom" in resp):
        passed += 1
    else:
        failed += 1

    # 5) Multiple interrupts then switch prompt still works
    sid = "stress-5"
    state = reset_session(sid, "dermatolog")
    _ = handle_unified_routing("kakšen je delovni čas", sid)
    resp = handle_unified_routing("imam bolečine v kolenu", sid) or ""
    pending = get_unified_state(sid).get("context", {}).get("pending_service_switch")
    ok = pending == "ortoped" and "Želite preklopiti" in resp
    if check("5. Več interruptov + pravilen pending switch", ok):
        passed += 1
    else:
        failed += 1

    print("\n" + "=" * 56)
    print(f"REZULTAT: {passed}/5 PASS, {failed}/5 FAIL")
    print("=" * 56)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
