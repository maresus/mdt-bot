#!/usr/bin/env python3
"""
Live capture test suite (real questions).
If the list is empty, the test is skipped.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.routing.unified_router import route  # noqa: E402


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "tests", "live_capture.json")

    with open(path, "r", encoding="utf-8") as f:
        cases: list[dict[str, Any]] = json.load(f)

    if not cases:
        print("LIVE CAPTURE - no cases (SKIPPED)")
        return 0

    total = len(cases)
    passed = 0
    failed = 0

    print("=" * 64)
    print(f"LIVE CAPTURE - Unified Routing ({total} cases)")
    print("=" * 64)

    for idx, case in enumerate(cases, start=1):
        name = case.get("name", f"LC{idx:02d}")
        message = case["message"]
        in_flow = bool(case.get("in_flow", False))
        state = {"flow": "appointment", "step": "date"} if in_flow else {"flow": "idle", "step": None}

        decision = route(message, state)

        intent_ok = decision.primary_intent.value == case["expected_intent"]
        service_expected = case.get("expected_service")
        action_expected = case.get("expected_action")

        service_ok = True if service_expected is None else decision.service_type == service_expected
        action_ok = True if action_expected is None else decision.action.value == action_expected

        ok = intent_ok and service_ok and action_ok
        if ok:
            passed += 1
            print(f"PASS [{idx:02d}] {name}")
        else:
            failed += 1
            print(f"FAIL [{idx:02d}] {name}")
            print(
                "  expected="
                f"intent:{case['expected_intent']} service:{service_expected} action:{action_expected}"
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
