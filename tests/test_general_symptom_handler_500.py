from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import pytest

from app.services.routing.symptom_fallback import (
    looks_like_medical_statement,
    looks_like_symptom_report,
)
from app.services.routing.symptom_general_handler import (
    build_general_symptom_clarify_reply,
    should_handle_general_symptom_message,
)
from app.services.routing.unified_router import IntentType


@dataclass(frozen=True)
class Case:
    case_id: str
    message: str
    intent: IntentType
    service_type: str | None
    in_flow: bool
    expected: bool


def _build_cases() -> list[Case]:
    cases: list[Case] = []
    seen: set[tuple[str, str, str, bool]] = set()

    def add(kind: str, message: str, intent: IntentType, service_type: str | None, in_flow: bool, expected: bool) -> None:
        key = (message, intent.name, str(service_type), in_flow)
        if key in seen:
            return
        seen.add(key)
        cases.append(Case(f"{kind}_{len(cases)+1:03d}", message, intent, service_type, in_flow, expected))

    positive_msgs = [
        "bulo mam",
        "bulo mam na hrbtu",
        "imam bulo",
        "glava me boli",
        "glavobol mam 3 dni",
        "neki me pece po kozi",
        "izpuscaj imam po rokah",
        "srbi me koza",
        "madez mam na kozi",
        "sumljiv madez krvavi",
        "krvavim iz nosa",
        "tezko diham",
        "vrocina in vrti se mi",
        "bruham in se mi vrti",
        "koleno boli in je oteceno",
        "zapestje sem si poskodoval",
        "prsni kos me boli",
        "boli me uho in glava",
        "bula pod pazduho",
        "mam izpuscaj pa srbi",
    ]
    positive_prefixes = ["", "zdwavo ", "prosim ", "ej ", "halo "]
    positive_suffixes = ["", " prosim", " kaj naj", " a to je ok", " ze 3 dni"]
    positive_intents = [IntentType.GENERAL, IntentType.BOOKING_APPOINTMENT, IntentType.SERVICE_INFO]

    for p, msg, s, intent in product(positive_prefixes, positive_msgs, positive_suffixes, positive_intents):
        full = f"{p}{msg}{s}".strip()
        add("POS", full, intent, None, False, True)
        if len(cases) >= 300:
            break

    # Same symptom-like messages should NOT trigger while already in booking flow or when service already identified.
    for msg, intent in product(positive_msgs[:15], positive_intents):
        add("NEG_FLOW", msg, intent, None, True, False)
        add("NEG_SERVICE", msg, intent, "DERMATOLOG", False, False)
        if len(cases) >= 420:
            break

    negative_msgs = [
        "zdravo",
        "hvala",
        "koliko stane botox",
        "kaksen je delovni cas",
        "rad bi termin pri dermatologu",
        "dermatolog",
        "26.2.2026",
        "08:30",
        "Marko Satler",
        "041123123",
        "mail je marko@test.si",
        "parkirni prostor imate",
        "kje se nahajate",
        "prestavil bi termin",
        "odpovej termin",
        "rabim napotnico za ortopeda",
        "botoc + filler kolk pride",
        "imam termin jutri",
        "ok",
        "da",
        "ne",
        "asdf qwer",
        "tnx",
        "kontakt",
        "info",
    ]
    negative_prefixes = ["", "prosim ", "halo ", "zdwavo "]
    negative_suffixes = ["", " prosim", "?", " zdaj"]
    all_intents = [
        IntentType.GENERAL,
        IntentType.BOOKING_APPOINTMENT,
        IntentType.SERVICE_INFO,
        IntentType.GREETING,
        IntentType.AFFIRMATIVE,
        IntentType.NEGATIVE,
    ]
    for p, msg, s, intent in product(negative_prefixes, negative_msgs, negative_suffixes, all_intents):
        full = f"{p}{msg}{s}".strip()
        add("NEG", full, intent, None, False, False)
        if len(cases) >= 500:
            break

    if len(cases) < 500:
        raise RuntimeError(f"Expected 500 cases, got {len(cases)}")
    return cases[:500]


CASES = _build_cases()


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_general_symptom_handler_500(case: Case) -> None:
    got = should_handle_general_symptom_message(
        message=case.message,
        primary_intent=case.intent,
        service_type=case.service_type,
        in_flow=case.in_flow,
        looks_like_symptom_report=looks_like_symptom_report,
        looks_like_medical_statement=looks_like_medical_statement,
    )
    assert got is case.expected, (
        f"{case.case_id}: intent={case.intent.name} service={case.service_type} "
        f"in_flow={case.in_flow} msg={case.message!r} got={got}"
    )


def test_build_general_symptom_clarify_reply_prefers_triage_fallback() -> None:
    triage = "Test triage odgovor.\n\nTo ni diagnoza."
    assert build_general_symptom_clarify_reply(triage_fallback=triage) == triage


def test_build_general_symptom_clarify_reply_default_contains_guidance_and_disclaimer() -> None:
    text = build_general_symptom_clarify_reply(triage_fallback=None)
    lowered = text.lower()
    assert "počitek" in lowered or "pocitek" in lowered
    assert "teko" in lowered
    assert "ni zdravniška diagnoza" in lowered or "ni zdravniska diagnoza" in lowered
    assert "koža" in lowered or "koza" in lowered


def test_general_symptom_handler_500_count() -> None:
    assert len(CASES) == 500
    assert len({(c.message, c.intent, c.service_type, c.in_flow) for c in CASES}) == 500

