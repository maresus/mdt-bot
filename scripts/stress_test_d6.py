#!/usr/bin/env python3
"""D6 stress + edge validation tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.chat_router import (  # type: ignore
    get_appointment_state,
    handle_appointment_booking,
    handle_unified_routing,
)
from app.services.session.unified_state import (  # type: ignore
    FlowStep,
    FlowType,
    get_unified_state,
    reset_unified_state,
    start_flow,
)


def _assert(name: str, cond: bool, detail: str = "") -> bool:
    status = "PASS" if cond else "FAIL"
    print(f"{status} | {name}")
    if not cond and detail:
        print(f"       {detail}")
    return cond


def _reset_booking(session_id: str, service: str = "dermatolog"):
    reset_unified_state(session_id)
    state = get_appointment_state(session_id)
    state["service_type"] = service
    state["step"] = "date"
    state["date"] = None
    state["time"] = None
    state["name"] = None
    state["phone"] = None
    state["email"] = None
    state["reason"] = None
    state["waiting_resume_confirmation"] = False
    start_flow(session_id, FlowType.APPOINTMENT, FlowStep.DATE)
    return state


def run_switch_stress(iterations: int = 100) -> tuple[int, int]:
    passed = 0
    failed = 0

    for i in range(1, iterations + 1):
        sid = f"d6-switch-{i}"
        state = _reset_booking(sid, "dermatolog")

        # 1) Suggest switch to ortoped
        r1 = handle_unified_routing("boli me koleno", sid) or ""
        c1 = "Želite preklopiti" in r1 and "Ortoped" in r1

        # 2) Confirm switch
        r2 = handle_unified_routing("da", sid) or ""
        c2 = state.get("service_type") == "ortoped" and "Kateri datum" in r2

        # 3) Trigger reverse suggestion, reject switch
        r3 = handle_unified_routing("imam izpuščaj", sid) or ""
        c3 = "Želite preklopiti" in r3 and "Dermatolo" in r3

        r4 = handle_unified_routing("ne", sid) or ""
        c4 = state.get("service_type") == "ortoped" and "Nadaljujemo z naročilom" in r4

        if c1 and c2 and c3 and c4:
            passed += 1
        else:
            failed += 1
            print(f"FAIL | switch-cycle-{i}")
            print(f"  c1={c1} c2={c2} c3={c3} c4={c4}")

    return passed, failed


def run_validation_edges() -> tuple[int, int]:
    passed = 0
    failed = 0

    sid = "d6-val-phone"
    state = _reset_booking(sid, "ortoped")
    state["date"] = "10.04.2026"
    state["time"] = "10:00"
    state["name"] = "Marko Satler"
    state["step"] = "phone"
    msg = handle_appointment_booking("abc", sid)
    if _assert("validation phone invalid", "veljavno telefonsko" in msg.lower(), msg):
        passed += 1
    else:
        failed += 1

    sid = "d6-val-email"
    state = _reset_booking(sid, "ortoped")
    state["date"] = "10.04.2026"
    state["time"] = "10:00"
    state["name"] = "Marko Satler"
    state["step"] = "email"
    state["phone"] = "041123123"
    msg = handle_appointment_booking("abc", sid)
    if _assert("validation email invalid", "veljaven email" in msg.lower(), msg):
        passed += 1
    else:
        failed += 1

    sid = "d6-val-date"
    state = _reset_booking(sid, "ortoped")
    state["step"] = "date"
    msg = handle_appointment_booking("12.4.2026", sid)  # Nedelja (pričakovano zavrnjen datum)
    date_ok = ("izberite drug datum" in msg.lower()) or ("od ponedeljka do petka" in msg.lower())
    if _assert("validation date format", date_ok, msg):
        passed += 1
    else:
        failed += 1

    sid = "d6-val-time"
    state = _reset_booking(sid, "ortoped")
    state["step"] = "time"
    state["date"] = "10.04.2026"
    msg = handle_appointment_booking("kadarkoli", sid)
    if _assert("validation time format", "povejte uro" in msg.lower()):
        passed += 1
    else:
        failed += 1

    return passed, failed


def main() -> int:
    print("=" * 68)
    print("D6 STRESS + EDGE TESTS")
    print("=" * 68)

    switch_ok, switch_fail = run_switch_stress(100)
    print(f"PASS | switch-stress summary {switch_ok}/100")

    val_ok, val_fail = run_validation_edges()

    total_ok = switch_ok + val_ok
    total_fail = switch_fail + val_fail
    total = 100 + 4

    print("-" * 68)
    print(f"RESULT: {total_ok}/{total} PASS, {total_fail}/{total} FAIL")

    # Sanity check: no stale pending switch context leaks
    sanity = get_unified_state("d6-switch-100").get("context", {}).get("pending_service_switch")
    if not _assert("sanity no stale pending switch", sanity is None):
        total_fail += 1

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
