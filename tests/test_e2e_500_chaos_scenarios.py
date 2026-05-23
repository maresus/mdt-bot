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


def _build_500_chaos_scenarios() -> list[Scenario]:
    scenarios: list[Scenario] = []
    seen: set[tuple[str, ...]] = set()

    def add(kind: str, turns: tuple[str, ...]) -> None:
        if turns in seen:
            return
        seen.add(turns)
        scenarios.append(Scenario(f"{kind}_{len(scenarios)+1:03d}", turns))

    openers = [
        "zdravo",
        "ej",
        "ojla",
        "halo",
        "neki ni ok",
        "a ste tu",
        "help pls",
        "yo",
        "idk kaj rabim",
        "kaj zdaj",
    ]
    nonsense = [
        "asdf qwer zxcv",
        "koleno bi jedel",
        "xxyyzz 123 ???",
        "rad bi termin pa ne bi termina",
        "neki me neki",
        "botoc filerrr ortopet",
        "nujno ampak ne nujno",
        "grem nikamor ampak kam",
        "hahaha ne vem",
        "blabla madez glava parkirisce",
    ]
    pivots = [
        "rad bi termin",
        "koliko stane",
        "kontakt",
        "kje ste",
        "imam bradavico",
        "glava me boli",
        "a rabim napotnco",
        "imam madez",
        "zapestje me boli",
        "lahko antibiotik",
    ]
    services = [
        "dermatologo",
        "ortopet",
        "okulsit",
        "laserski poseg",
        "estetski",
        "kozmetika",
        "fizioterapija",
        "okulist",
        "dermatolog",
        "ortoped",
    ]
    dates = [
        "25.2.",
        "26.02.2026",
        "jutri",
        "1.3.",
        "32.13.2026",
        "15.3026",
        "17.3.2026",
        "danes",
        "petek",
        "00.00.0000",
    ]
    endings = [
        "hvala",
        "adijo",
        "ok",
        "kaj predlagas",
        "daj termin",
        "lahko",
        "ne",
        "reset",
        "lp",
        "to je to",
    ]

    # 1) 300 deep mixed flows
    for o, n, p, s, d, e in product(openers, nonsense, pivots, services, dates, endings):
        add("CHAOS6", (o, n, p, s, d, e))
        if len(scenarios) >= 300:
            break

    # 2) 120 shorter contradictory flows
    contradiction = [
        "rad bi termin ampak ne bi termina",
        "hočem ceno ampak ne povem storitve",
        "imam bolecino pa ne vem kje",
        "prestavim termin ki ga nimam",
        "nujno ampak lahko caka",
        "imam vse izvide in nobenega",
        "ne vem ce sem jaz",
        "neki madez pa mogoce ni",
        "kdo je direktor pa kolko je botox",
        "a je parkirisce in operacija",
    ]
    followups = [
        "kaj zdaj",
        "lahko",
        "zrihtaj",
        "ne razumem",
        "ponovi",
        "dermatolog",
        "ortoped",
        "kontakt",
        "termin 25.2",
        "hvala",
        "adijo",
        "ok",
    ]
    for c, f1, f2, f3 in product(contradiction, followups, services, dates):
        add("CHAOS4", (c, f1, f2, f3))
        if len(scenarios) >= 420:
            break

    # 3) 80 gibberish + topic switches
    gib = [
        "### ???",
        "123 123 123",
        "😵‍💫 ???",  # user-like garbage
        "q q q q",
        "....",
        "---",
        "neki",
        "zzzz",
        "kaj pa vse ostalo",
        "a lahko vse",
    ]
    topic = [
        "mate parkirni prostor",
        "koliko cakam",
        "imam bulo",
        "glava me boli",
        "koliko je filler",
        "a rabim napotnco",
        "rad bi termin",
        "kaksen delovni cas",
        "kontakt",
        "kdo je direktor",
    ]
    for g, t, s, e in product(gib, topic, services, endings):
        add("CHAOS_SWITCH", (g, t, s, e))
        if len(scenarios) >= 500:
            break

    return scenarios[:500]


SCENARIOS = _build_500_chaos_scenarios()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.scenario_id for s in SCENARIOS])
def test_e2e_500_chaos_live_like(client: TestClient, scenario: Scenario) -> None:
    session_id = f"e2e500-chaos-{scenario.scenario_id.lower()}"

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
    # Bot must stay in safe/helpful domain even for nonsense/mixed inputs
    assert any(
        token in merged
        for token in (
            "termin",
            "pregled",
            "dermat",
            "ortoped",
            "okul",
            "kontakt",
            "telefon",
            "email",
            "delovni cas",
            "naslov",
            "zdravnik",
            "pomagam",
            "usmerim",
            "kateri datum",
            "katera ura",
            "prosti termini",
            "poklicite",
            "112",
            "cena",
        )
    ), f"No useful routing/help signal in transcript: {scenario.scenario_id}"


def test_e2e_500_chaos_are_unique() -> None:
    assert len(SCENARIOS) == 500
    turns = [s.turns for s in SCENARIOS]
    assert len(set(turns)) == 500
