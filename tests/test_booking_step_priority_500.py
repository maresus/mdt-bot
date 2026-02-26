from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any

import pytest

from app.services.flows.booking_interrupt_policy import (
    BookingInterruptDeps,
    should_prioritize_booking_step_input,
)
from app.services.routing.unified_router import IntentType
from app.services.routing.parsers import (
    extract_date_from_message,
    extract_time_from_message,
    extract_service_type,
    is_likely_full_name,
)


def _dummy(*args: Any, **kwargs: Any) -> Any:
    return None


DEPS = BookingInterruptDeps(
    is_in_flow=lambda session_id: True,
    get_current_step=lambda session_id: None,
    get_appointment_data=lambda session_id: {},
    get_context_value=lambda session_id, key, default=None: default,
    set_context_value=lambda session_id, key, value: None,
    extract_date_from_message=extract_date_from_message,
    extract_time_from_message=extract_time_from_message,
    extract_service_type=lambda msg: extract_service_type(msg, clinic_id="lj_center"),
    is_likely_full_name=is_likely_full_name,
    build_interrupt_response=lambda answer, step, show_resume: answer,
    build_resume_prompt=lambda step, state: "resume",
    interrupt_answer=lambda **kwargs: None,
    get_info_response=lambda key: "",
    get_service_info=lambda service: None,
    looks_like_symptom_report=lambda msg: False,
    symptom_advice=lambda message, service: "",
)


@dataclass(frozen=True)
class Case:
    case_id: str
    step: str | None
    data: dict[str, Any]
    message: str
    expected: bool
    intent: IntentType | None = None
    service_hint: str | None = None


def _build_cases() -> list[Case]:
    cases: list[Case] = []
    seen: set[tuple[str, str, str]] = set()

    def add(kind: str, step: str | None, data: dict[str, Any], message: str, expected: bool, intent: IntentType | None = None, service_hint: str | None = None) -> None:
        key = (str(step), str(sorted(data.items())), message)
        if key in seen:
            return
        seen.add(key)
        cases.append(Case(f"{kind}_{len(cases)+1:03d}", step, data, message, expected, intent, service_hint))

    # 1) Date step (120)
    date_inputs = ["15.3.2026", "15.3.", "jutri", "danes", "26.02.2026"]
    noise = ["ok", "asdf", "ne vem", "kontakt", "koliko stane", "halo"]
    for msg in date_inputs:
        add("DATE_POS", "date", {"service_type": "DERMATOLOG"}, msg, True)
        add("DATE_POS_NONE_STEP", None, {"service_type": "DERMATOLOG"}, msg, True)  # inferred date
    for msg in noise:
        add("DATE_NEG", "date", {"service_type": "DERMATOLOG"}, msg, False)
    # expand combinations
    for prefix, msg in product(["", "prosim ", "zdwavo "], date_inputs):
        add("DATE_POS2", "date", {"service_type": "ORTOPED"}, f"{prefix}{msg}", True)
        if len(cases) >= 120:
            break

    # 2) Time step (120)
    time_inputs = ["8:00", "08:00", "09:30", "ob 10", "ob 11:30", "12.00"]
    for msg in time_inputs:
        add("TIME_POS", "time", {"service_type": "DERMATOLOG", "date": "15.03.2026"}, msg, True)
        add("TIME_POS_INFER", None, {"service_type": "DERMATOLOG", "date": "15.03.2026"}, msg, True)
    for msg in noise:
        add("TIME_NEG", "time", {"service_type": "DERMATOLOG", "date": "15.03.2026"}, msg, False)
    for prefix, msg in product(["", "ok ", "prosim "], time_inputs):
        add("TIME_POS2", "time", {"service_type": "OKULIST", "date": "17.03.2026"}, f"{prefix}{msg}", True)
        if len(cases) >= 240:
            break

    # 3) Service selection step (100)
    service_msgs = ["dermatolog", "dermatologo", "ortopet", "okulsit", "laserski poseg", "estetski", "kozmetika"]
    for msg in service_msgs:
        add("SERV_POS", "select_service", {}, msg, True)
        add("SERV_POS_NONE", None, {}, msg, True)
        add("SERV_POS_HINT", "select_service", {}, "neki", True, service_hint="DERMATOLOG")
    for msg in noise:
        add("SERV_NEG", "select_service", {}, msg, False)
    for prefix, suffix, msg in product(["", "rad bi ", "pri ", "za "], ["", " prosim", " zdaj", " cimprej"], service_msgs):
        add("SERV_POS2", "select_service", {}, f"{prefix}{msg}{suffix}", True)
        if len(cases) >= 340:
            break

    # 4) Name/phone/email/reason/confirm (160)
    names = ["Marko Satler", "Ana Novak", "Maja Horvat", "Luka Zupan", "Nina Kralj"]
    phones = ["041123123", "+38641111222", "031 555 666", "040-222-333", "+386 31 123 456"]
    emails = ["a@b.si", "marko@test.com", "ana.novak@gmail.com", "x@y.eu", "oseba@firma.si"]
    reasons = ["madez na kozi", "bolece koleno", "pregled vida", "bradavica", "kontrola"]
    yesno = [(IntentType.AFFIRMATIVE, "da"), (IntentType.NEGATIVE, "ne"), (IntentType.AFFIRMATIVE, "ok"), (IntentType.NEGATIVE, "ne hvala")]

    for m in names:
        add("NAME_POS", "name", {"service_type": "DERMATOLOG", "date": "15.03.2026", "time": "10:00"}, m, True)
    for p in phones:
        add("PHONE_POS", "phone", {"service_type": "DERMATOLOG", "date": "15.03.2026", "time": "10:00", "name": "Marko Satler"}, p, True)
    for e in emails:
        add("EMAIL_POS", "email", {"service_type": "DERMATOLOG", "date": "15.03.2026", "time": "10:00", "name": "Marko Satler", "phone": "+38641111222"}, e, True)
    for r in reasons:
        add("REASON_POS", "reason", {"service_type": "DERMATOLOG", "date": "15.03.2026", "time": "10:00", "name": "Marko Satler", "phone": "+38641111222", "email": "a@b.si"}, r, True)
    for intent, msg in yesno:
        add("CONFIRM_POS", "confirm", {"service_type": "DERMATOLOG", "date": "15.03.2026", "time": "10:00", "name": "Marko Satler", "phone": "+38641111222", "email": "a@b.si", "reason": "madez"}, msg, True, intent=intent)

    negatives_by_step = [
        ("name", "mk"),
        ("phone", "ne vem"),
        ("email", "brez maila"),
        ("confirm", "mogoce"),
    ]
    for step, msg in negatives_by_step:
        add("STEP_NEG", step, {"service_type": "DERMATOLOG", "date": "15.03.2026", "time": "10:00", "name": "Marko Satler", "phone": "+38641111222", "email": "a@b.si", "reason": "madez"}, msg, False)

    # Fill to exactly 500 with inferred-step cases
    inferred_msgs = [
        ("15.3.2026", {"service_type": "OKULIST"}),
        ("08:30", {"service_type": "OKULIST", "date": "15.03.2026"}),
        ("Marko Satler", {"service_type": "OKULIST", "date": "15.03.2026", "time": "08:30"}),
        ("041111111", {"service_type": "OKULIST", "date": "15.03.2026", "time": "08:30", "name": "Marko Satler"}),
        ("marko@test.com", {"service_type": "OKULIST", "date": "15.03.2026", "time": "08:30", "name": "Marko Satler", "phone": "041111111"}),
        ("pregled vida", {"service_type": "OKULIST", "date": "15.03.2026", "time": "08:30", "name": "Marko Satler", "phone": "041111111", "email": "marko@test.com"}),
        ("da", {"service_type": "OKULIST", "date": "15.03.2026", "time": "08:30", "name": "Marko Satler", "phone": "041111111", "email": "marko@test.com", "reason": "pregled vida"}),
    ]
    variant_idx = 0
    while len(cases) < 500:
        for msg, data in inferred_msgs:
            intent = IntentType.AFFIRMATIVE if msg == "da" else None
            if msg == "da":
                variant_msg = msg
            elif "@" in msg:
                local, domain = msg.split("@", 1)
                variant_msg = f"{local}+{variant_idx}@{domain}"
            elif msg == "Marko Satler":
                variant_msg = msg
            elif any(ch.isdigit() for ch in msg):
                variant_msg = f"{msg} {variant_idx}".strip()
            else:
                variant_msg = f"{msg} {variant_idx}"
            add("INFER", None, data, variant_msg, True, intent=intent)
            if len(cases) >= 500:
                break
        variant_idx += 1
        if variant_idx > 200:
            raise RuntimeError(f"Failed to build 500 unique cases, got {len(cases)}")

    return cases[:500]


CASES = _build_cases()


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_booking_step_priority_500(case: Case) -> None:
    got = should_prioritize_booking_step_input(
        message=case.message,
        step=case.step,
        appointment_data=case.data,
        deps=DEPS,
        decision_intent=case.intent,
        service_hint=case.service_hint,
    )
    assert got is case.expected, f"{case.case_id}: step={case.step}, data={case.data}, message={case.message!r}, got={got}"


def test_booking_step_priority_500_count() -> None:
    assert len(CASES) == 500
