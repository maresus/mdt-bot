#!/usr/bin/env python3
"""D3 module smoke tests: formatter + interrupt flow."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.response_formatter import format_response  # noqa: E402
from app.services.flows.interrupt_flow import InterruptFlowDeps, resolve_interrupt_answer  # noqa: E402
from app.services.routing.unified_router import IntentType  # noqa: E402


def _info(key: str) -> str:
    return {
        "lokacija": "Lokacija info",
        "parkiranje": "Parking info",
        "storitve": "Storitve info",
        "cene": "Cene info",
        "kontakt": "Kontakt info",
    }.get(key, "Kontakt info")


def _price(service: str | None) -> str:
    return f"Cena za {service or 'splošno'}"


def _service(service: str):
    return {
        "ortoped": {"name": "Ortopedski pregled", "duration_minutes": 30, "price_range": "40-80 €"}
    }.get(service)


def test_formatter() -> bool:
    payload = format_response("Pozdrav", metadata={"contract_version": "v0.1"})
    return payload["text"] == "Pozdrav" and payload["metadata"].get("contract_version") == "v0.1"


def test_interrupt_info() -> bool:
    deps = InterruptFlowDeps(get_info_response=_info, service_price_info=_price, get_service_info=_service)
    answer = resolve_interrupt_answer(
        message="imate parking",
        primary_intent=IntentType.INFO,
        service_hint=None,
        active_service=None,
        deps=deps,
    )
    return answer == "Parking info"


def test_interrupt_price() -> bool:
    deps = InterruptFlowDeps(get_info_response=_info, service_price_info=_price, get_service_info=_service)
    answer = resolve_interrupt_answer(
        message="koliko stane",
        primary_intent=IntentType.PRICE,
        service_hint="ORTOPED",
        active_service=None,
        deps=deps,
    )
    return answer == "Cena za ortoped"


def main() -> int:
    tests = [
        ("formatter payload", test_formatter),
        ("interrupt info", test_interrupt_info),
        ("interrupt price", test_interrupt_price),
    ]

    ok = 0
    fail = 0
    for name, fn in tests:
        if fn():
            print(f"PASS | {name}")
            ok += 1
        else:
            print(f"FAIL | {name}")
            fail += 1

    print(f"RESULT: {ok}/{len(tests)} pass, {fail}/{len(tests)} fail")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
