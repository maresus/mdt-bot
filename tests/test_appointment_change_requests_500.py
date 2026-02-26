from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import pytest

from app.services.routing.appointment_change_requests import (
    detect_appointment_change_request,
    build_appointment_change_reply,
)


@dataclass(frozen=True)
class Case:
    case_id: str
    message: str
    expected: str | None


def _build_cases() -> list[Case]:
    cases: list[Case] = []
    seen: set[str] = set()

    def add(kind: str, message: str, expected: str | None) -> None:
        if message in seen:
            return
        seen.add(message)
        cases.append(Case(f"{kind}_{len(cases)+1:03d}", message, expected))

    # 1) Reschedule variants (200)
    starters = [
        "rad bi",
        "rada bi",
        "prosim",
        "lahko",
        "nujno",
        "zdwavo",
        "ej",
        "",
    ]
    verbs = [
        "prestavil",
        "prestavim",
        "prestavitev",
        "prestavi",
        "premaknil",
        "premaknem",
        "spremenil",
        "spremenim",
    ]
    objects = [
        "termin",
        "pregled",
        "dogovorjen termin",
        "naročilo",
        "rezervacijo termina",
    ]
    tails = [
        "na naslednji teden",
        "na drug datum",
        "na jutri",
        "ker ne morem",
        "prosim",
    ]
    for s, v, o, t in product(starters, verbs, objects, tails):
        msg = " ".join(x for x in [s, v, o, t] if x).strip()
        add("RES", msg, "reschedule")
        if len(cases) >= 200:
            break

    # 2) Cancel variants (200)
    cancel_verbs = [
        "odpovej",
        "odpoved",
        "preklic",
        "preklici",
        "preklicem",
        "cancel",
        "odjavi",
    ]
    cancel_tails = ["termin", "pregled", "dogovorjen termin", "naročilo", "rezervacijo"]
    reasons = ["", "prosim", "ker ne morem", "ne pridem", "danes"]
    for s, v, o, r in product(starters, cancel_verbs, cancel_tails, reasons):
        msg = " ".join(x for x in [s, v, o, r] if x).strip()
        add("CAN", msg, "cancel")
        if len(cases) >= 400:
            break

    # 3) Negatives / ambiguous should not trigger (100)
    negatives = [
        "rad bi termin",
        "koliko je termin",
        "prestavna roka",
        "odpoved ledvic",
        "cancel culture",
        "naslednji teden bi prisel na pregled",
        "drug termin me zanima",
        "prestavitev omare",
        "preklic narocnine",
        "ne pridem mogoce",
        "odpovedat hočem email",
        "kdaj je termin",
        "a imate termin",
        "termin jutri ob 9",
        "prestaviva mizo",
        "odpovej sms opomnik",
        "preklic aplikacije",
        "cancel account",
        "drug datum za prvi termin",
        "naročil bi pregled",
    ]
    prefixes = ["", "zdwavo ", "ej ", "prosim ", "halo "]
    suffixes = ["", " prosim", " ?", " danes", " jutri"]
    for p, n, s in product(prefixes, negatives, suffixes):
        add("NEG", f"{p}{n}{s}".strip(), None)
        if len(cases) >= 500:
            break

    return cases[:500]


CASES = _build_cases()


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_detect_appointment_change_request_500(case: Case) -> None:
    assert detect_appointment_change_request(case.message) == case.expected


def test_build_appointment_change_reply_includes_contact() -> None:
    text = build_appointment_change_reply("reschedule", phone="02 601 54 00", email="info@test.si")
    assert "klepeta" in text.lower()
    assert "02 601 54 00" in text
    assert "info@test.si" in text


def test_appointment_change_requests_500_count() -> None:
    assert len(CASES) == 500
    assert len({c.message for c in CASES}) == 500

