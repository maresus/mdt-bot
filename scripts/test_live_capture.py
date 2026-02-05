#!/usr/bin/env python3
"""
Live capture test suite with dialog sequences.
Supports:
- flat cases: {message, expected_intent, expected_service?, expected_action?, in_flow?}
- dialogs: {name, dialog:[{message, expected_intent?, expected_service?, expected_action?, expect_contains?, expect_contains_any?}]}
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.routing.unified_router import route  # noqa: E402
from app.services.session.unified_state import reset_unified_state, get_unified_state, is_in_flow  # noqa: E402
from app.services.chat_router import (  # noqa: E402
    handle_unified_routing,
    handle_appointment_booking,
    reset_appointment_state,
    get_appointment_state,
)


def _run_message(session_id: str, message: str) -> str:
    response = handle_unified_routing(message, session_id)
    if response is None and is_in_flow(session_id):
        response = handle_appointment_booking(message, session_id)
    return response or ""


def _check_contains(response: str, expect: str | list[str] | None) -> bool:
    if not expect:
        return True
    if isinstance(expect, str):
        return expect.lower() in response.lower()
    return any(e.lower() in response.lower() for e in expect)


def _check_intent(message: str, state: dict[str, Any], expected_intent: str | None) -> tuple[bool, str]:
    if not expected_intent:
        return True, ""
    decision = route(message, state)
    ok = decision.primary_intent.value == expected_intent
    detail = f"got={decision.primary_intent.value}" if not ok else ""
    return ok, detail


def _check_service_action(message: str, state: dict[str, Any], expected_service: str | None, expected_action: str | None) -> tuple[bool, str]:
    if expected_service is None and expected_action is None:
        return True, ""
    decision = route(message, state)
    ok_service = True if expected_service is None else decision.service_type == expected_service
    ok_action = True if expected_action is None else decision.action.value == expected_action
    ok = ok_service and ok_action
    detail = f"got_service={decision.service_type} got_action={decision.action.value}" if not ok else ""
    return ok, detail


def _reset_session(session_id: str) -> None:
    reset_unified_state(session_id)
    reset_appointment_state(get_appointment_state(session_id))


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "tests", "live_capture.json")

    with open(path, "r", encoding="utf-8") as f:
        cases: list[dict[str, Any]] = json.load(f)

    if not cases:
        print("LIVE CAPTURE - no cases (SKIPPED)")
        return 0

    total = 0
    passed = 0
    failed = 0

    print("=" * 64)
    print(f"LIVE CAPTURE - Dialog Sequences ({len(cases)} cases)")
    print("=" * 64)

    for idx, case in enumerate(cases, start=1):
        name = case.get("name", f"LC{idx:02d}")
        session_id = f"live-{idx:02d}"
        _reset_session(session_id)

        dialog = case.get("dialog")
        if dialog:
            ok_dialog = True
            for step_idx, step in enumerate(dialog, start=1):
                total += 1
                message = step["message"]
                expected_intent = step.get("expected_intent")
                expected_service = step.get("expected_service")
                expected_action = step.get("expected_action")
                expect_contains = step.get("expect_contains")
                expect_contains_any = step.get("expect_contains_any")

                state = get_unified_state(session_id)
                ok_intent, detail_intent = _check_intent(message, state, expected_intent)
                ok_sa, detail_sa = _check_service_action(message, state, expected_service, expected_action)

                response = _run_message(session_id, message)
                ok_contains = _check_contains(response, expect_contains) and _check_contains(response, expect_contains_any)

                ok = ok_intent and ok_sa and ok_contains
                if ok:
                    passed += 1
                    print(f"PASS [{idx:02d}.{step_idx:02d}] {name}")
                else:
                    failed += 1
                    ok_dialog = False
                    print(f"FAIL [{idx:02d}.{step_idx:02d}] {name}")
                    if detail_intent:
                        print(f"  intent: {detail_intent}")
                    if detail_sa:
                        print(f"  service/action: {detail_sa}")
                    if not ok_contains:
                        print("  response did not contain expected text")
            if not ok_dialog:
                print("  dialog failed")
        else:
            total += 1
            message = case["message"]
            expected_intent = case.get("expected_intent")
            expected_service = case.get("expected_service")
            expected_action = case.get("expected_action")
            in_flow = bool(case.get("in_flow", False))
            state = {"flow": "appointment", "step": "date"} if in_flow else {"flow": "idle", "step": None}
            decision = route(message, state)

            intent_ok = decision.primary_intent.value == expected_intent if expected_intent else True
            service_ok = True if expected_service is None else decision.service_type == expected_service
            action_ok = True if expected_action is None else decision.action.value == expected_action

            ok = intent_ok and service_ok and action_ok
            if ok:
                passed += 1
                print(f"PASS [{idx:02d}] {name}")
            else:
                failed += 1
                print(f"FAIL [{idx:02d}] {name}")
                print(
                    "  expected="
                    f"intent:{expected_intent} service:{expected_service} action:{expected_action}"
                )
                print(
                    "  got="
                    f"intent:{decision.primary_intent.value} service:{decision.service_type} action:{decision.action.value}"
                )

    print("-" * 64)
    print(f"RESULT: {passed}/{total} passed, {failed}/{total} failed")

    if failed == 0:
        print("LIVE CAPTURE PASS (100%)")
        return 0

    print("LIVE CAPTURE FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
