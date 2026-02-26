from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import pytest

from app.services.routing.unified_router import route as unified_route, IntentType
from app.services.routing.message_normalizer import normalize_user_message


@dataclass(frozen=True)
class Case:
    case_id: str
    message: str
    expected_any: tuple[IntentType, ...]


def _state() -> dict:
    return {"flow": "idle", "context": {"clinic_id": "lj_center"}}


def _build_cases() -> list[Case]:
    cases: list[Case] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, message: str, expected: IntentType | tuple[IntentType, ...]) -> None:
        expected_any = expected if isinstance(expected, tuple) else (expected,)
        key = (message, ",".join(e.value for e in expected_any))
        if key in seen:
            return
        seen.add(key)
        cases.append(Case(f"{kind}_{len(cases)+1:03d}", message, expected_any))

    greetings = ["zdwavo", "zdravjo", "zdravo", "živjo", "zivjo", "hej", "halo", "pozdravljeni", "dober dan", "ej"]
    noise = ["", "!", "!!", "...", " :)"]
    for g, n in product(greetings, noise):
        add("GREET", f"{g}{n}", IntentType.GREETING)

    booking_heads = ["rad bi termin", "rada bi termin", "rad bi se narocil", "rabim pregled", "lahko rezerviram termin"]
    services = ["dermatologo", "dermatalog", "ortopet", "okulsit", "laser", "estetski", "kozmetika"]
    booking_suffixes = ["", " prosim", " cimprej", " jutri", " danes", " ob 9", " 26.2."]
    for h, s, suf in product(booking_heads, services, booking_suffixes):
        add("BOOK", f"{h} za {s}", (IntentType.BOOKING_APPOINTMENT, IntentType.URGENCY))
        add("BOOK2", f"{h} pri {s}{suf}", (IntentType.BOOKING_APPOINTMENT, IntentType.URGENCY))

    price_q = ["kolk stane", "kolko stane", "koliko stane", "cenik za", "cena za"]
    price_services = ["botoc", "filer", "ortopet", "dermatologo", "okulsit", "laserski poseg"]
    for q, s in product(price_q, price_services):
        add("PRICE", f"{q} {s}", IntentType.PRICE)

    info_q = [
        "mate parkirni prostor",
        "kolk cakam",
        "kaksn delovni cas",
        "kje ste",
        "kontakt pls",
        "a rabim napotnco",
    ]
    tails = ["", "?", " prosim", " danes", " jutri"]
    info_prefix = ["", "zdwavo ", "ej ", "prosim "]
    for pfx, q, t in product(info_prefix, info_q, tails):
        # mixed bucket can route as INFO or GENERAL depending on phrase; we select deterministic INFO-like phrases only
        if "napotnco" in q:
            expected = (IntentType.INFO, IntentType.GENERAL, IntentType.SERVICE_INFO, IntentType.URGENCY)
        else:
            expected = (IntentType.INFO, IntentType.URGENCY)
        add("INFO", f"{pfx}{q}{t}", expected)

    symptom_msgs = [
        "mam madez",
        "imam izpuscaj",
        "zapestje me boli",
        "bradavico imam",
        "pece me koza",
        "koleno me boli",
        "glava me boli",
        "krvavim iz nosa",
        "neki me pece po kozi",
        "sumljiv madez",
    ]
    symptom_wrappers = ["{s}", "zdwavo {s}", "ej {s} kaj naj", "{s} prosim", "mam to: {s}", "neki: {s}"]
    for s, wrap in product(symptom_msgs, symptom_wrappers):
        expected = (IntentType.SERVICE_INFO, IntentType.UNSUPPORTED_SYMPTOM, IntentType.URGENCY, IntentType.GENERAL)
        add("SYM", wrap.format(s=s), expected)
        if len(cases) >= 500:
            break

    return cases[:500]


CASES = _build_cases()


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_routing_500_typos(case: Case) -> None:
    normalized = normalize_user_message(case.message)
    decision = unified_route(normalized, _state())
    assert decision.primary_intent in case.expected_any, (
        f"{case.case_id}: message={case.message!r}, normalized={normalized!r}, "
        f"got={decision.primary_intent}, expected_any={case.expected_any}"
    )


def test_routing_500_typos_case_count() -> None:
    assert len(CASES) == 500
    assert len({c.message for c in CASES}) == 500
