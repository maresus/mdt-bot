from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.chat_router import router as chat_router


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    turns: tuple[str, ...]


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(chat_router)
    return TestClient(app)


def _norm(text: str) -> str:
    return (
        (text or "")
        .lower()
        .replace("š", "s")
        .replace("č", "c")
        .replace("ž", "z")
        .replace("ć", "c")
        .replace("đ", "d")
    )


def _build_500_nonsense_scenarios() -> list[Scenario]:
    scenarios: list[Scenario] = []
    seen_turns: set[tuple[str, ...]] = set()

    def add(kind: str, turns: tuple[str, ...]) -> None:
        if turns in seen_turns:
            return
        seen_turns.add(turns)
        scenarios.append(Scenario(f"{kind}_{len(scenarios)+1:03d}", turns))

    openers = [
        "zdravo",
        "oj",
        "halo",
        "ej",
        "a ste tam",
        "help",
        "neki rabim",
        "ne vem kaj rabim",
        "kaj zdaj",
        "yo",
    ]
    nonsense = [
        "asdf asdf qwe",
        "koleno bi jedel",
        "000 ???",
        "kr neki me neki",
        "imam vse in nic",
        "rad bi termin brez termina",
        "botoc filr ortopet",
        "x x x",
        "......",
        "neki",
    ]
    pivots = [
        "rad bi termin",
        "koliko stane",
        "kontakt",
        "kje ste",
        "imam madez",
        "zapestje me boli",
        "glava me boli",
        "rabim napotnico",
        "lahko antibiotik",
        "koliko cakam",
    ]
    services = [
        "dermatolog",
        "ortoped",
        "okulist",
        "laserski poseg",
        "estetski poseg",
        "kozmetika",
        "dermatologo",
        "ortopet",
        "okulsit",
        "laser",
    ]
    dates = [
        "25.2.",
        "26.02.2026",
        "jutri",
        "danes",
        "17.3.2026",
        "15.3026",
        "32.13.2026",
        "1.3.",
        "petek",
        "00.00.0000",
    ]
    closers = [
        "hvala",
        "ok",
        "ne",
        "lahko",
        "ponovi",
        "kaj predlagas",
        "lp",
        "adijo",
        "reset",
        "to je to",
    ]

    # 1) Long mixed nonsense booking-like chains (220)
    for o, n, p, s, d, c in product(openers, nonsense, pivots, services, dates, closers):
        add("NONSENSE6", (o, n, p, s, d, c))
        if len(scenarios) >= 220:
            break

    # 2) Contradictory short chains (140)
    contradictions = [
        "hocem termin ampak ne hocem termina",
        "hocem ceno ampak brez storitve",
        "prestavim termin ki ga nimam",
        "nujno ampak lahko caka",
        "imam izvide pa jih nimam",
        "vse me boli in nic me ne boli",
        "rad bi vse storitve hkrati",
        "sem nov in sem ze bil",
        "narocilo brez podatkov",
        "zakljuci pa nadaljuj",
    ]
    followups = [
        "kaj zdaj",
        "lahko",
        "zrihtaj",
        "ne razumem",
        "kontakt",
        "rad bi termin",
        "koliko je botox",
        "imam bulo",
        "kdo je direktor",
        "parkirisce",
    ]
    for c0, f1, f2, f3 in product(contradictions, followups, services, dates):
        add("NONSENSE4", (c0, f1, f2, f3))
        if len(scenarios) >= 360:
            break

    # 3) Topic whiplash with typos and slang (100)
    topic1 = [
        "mam bradavico",
        "botoc + filer kolk skp",
        "zapestje sem sfukal",
        "glava me razbija",
        "mam madez",
        "rabim dermatologa al ortopeda",
        "a mate parking",
        "kolk cakam",
        "a rabim napotnco",
        "a delate v soboto",
    ]
    topic2 = [
        "ok pa se termin",
        "ne termin sam cena",
        "daj kontakt",
        "kje tocno ste",
        "jutri ob 9",
        "26.2. ob 11",
        "18.3.2026",
        "neki ne stekam",
        "dej po domac",
        "hvala lp",
    ]
    for t1, t2, s in product(topic1, topic2, services):
        add("WHIPLASH3", (t1, t2, s))
        if len(scenarios) >= 460:
            break

    # 4) Gibberish + abrupt booking asks (40)
    gibberish = [
        "###",
        "123123",
        "qqqq",
        "---",
        "???",
        "nwm",
        "a",
        "b",
        "x",
        "zzz",
    ]
    abrupt = [
        "rad bi termin",
        "kateri datum",
        "katera ura",
        "na kateri pregled",
        "okulist",
        "dermatolog",
        "ortoped",
        "kontakt",
        "koliko stane",
        "adijo",
    ]
    for g, a, d in product(gibberish, abrupt, dates):
        add("GIB3", (g, a, d))
        if len(scenarios) >= 500:
            break

    return scenarios[:500]


SCENARIOS = _build_500_nonsense_scenarios()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.scenario_id for s in SCENARIOS])
def test_e2e_500_nonsense_live_like(client: TestClient, scenario: Scenario) -> None:
    session_id = f"e2e500-nonsense-{scenario.scenario_id.lower()}"

    transcript: list[str] = []
    for message in scenario.turns:
        response = client.post(
            "/chat/",
            json={
                "message": message,
                "session_id": session_id,
                "clinic_id": "test_center",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        reply = str(payload.get("reply", "")).strip()
        assert reply

        lower = _norm(reply)
        assert "internal server error" not in lower
        assert "traceback" not in lower
        assert "prislo je do napake pri povezavi" not in lower

        transcript.append(lower)

    merged = "\n".join(transcript)
    # For nonsense inputs bot must still provide some routing, support, or safety signal.
    assert any(
        token in merged
        for token in (
            "termin",
            "pregled",
            "na kateri pregled",
            "kateri datum",
            "katera ura",
            "prosti termini",
            "dermat",
            "ortoped",
            "okul",
            "kontakt",
            "telefon",
            "email",
            "naslov",
            "delovni cas",
            "cena",
            "pomagam",
            "usmerim",
            "zdravnik",
            "poklicite",
            "112",
        )
    ), f"No useful support signal found for scenario {scenario.scenario_id}"


def test_e2e_500_nonsense_are_unique() -> None:
    assert len(SCENARIOS) == 500
    turns = [s.turns for s in SCENARIOS]
    assert len(set(turns)) == 500
