#!/usr/bin/env python3
"""Shared runner for routing JSON suites."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.routing.unified_router import route


@dataclass
class TestRunner:
    name: str
    passed: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)

    def test(self, case: dict[str, Any], idx: int) -> None:
        case_name = str(case["name"])
        message = str(case["message"])
        in_flow = bool(case.get("in_flow", False))
        state = {"flow": "appointment", "step": "date"} if in_flow else {"flow": "idle", "step": None}
        decision = route(message, state)

        expected_intent = str(case["expected_intent"])
        expected_service = case.get("expected_service")
        expected_action = case.get("expected_action")

        intent_ok = decision.primary_intent.value == expected_intent
        service_ok = True if expected_service is None else decision.service_type == expected_service
        action_ok = True if expected_action is None else decision.action.value == expected_action
        ok = intent_ok and service_ok and action_ok

        if ok:
            self.passed += 1
            print(f"PASS [{idx:02d}] {case_name}")
            return

        self.failed += 1
        details = (
            f"FAIL [{idx:02d}] {case_name}\n"
            f"  expected=intent:{expected_intent} service:{expected_service} action:{expected_action}\n"
            f"  got=intent:{decision.primary_intent.value} service:{decision.service_type} action:{decision.action.value}"
        )
        self.failures.append(details)
        print(details)

    def run_from_json(self, path: str | Path) -> int:
        suite_path = Path(path)
        cases = json.loads(suite_path.read_text(encoding="utf-8"))
        total = len(cases)

        print("=" * 64)
        print(f"{self.name} ({total} cases)")
        print("=" * 64)
        for idx, case in enumerate(cases, start=1):
            self.test(case, idx)
        print("-" * 64)
        print(f"RESULT: {self.passed}/{total} passed, {self.failed}/{total} failed")
        return 0 if self.failed == 0 else 1
