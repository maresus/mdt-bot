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
    expect_any_final: tuple[str, ...]


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(chat_router)
    return TestClient(app)


def _build_500_unique_scenarios() -> list[Scenario]:
    scenarios: list[Scenario] = []
    seen_turns: set[tuple[str, ...]] = set()
    booking_progress_expect = (
        "na kateri pregled",
        "kateri datum",
        "prosti termini",
        "katera ura",
        "ime in priimek",
        "telefons",
        "email",
    )

    def add(kind: str, turns: tuple[str, ...], expect: tuple[str, ...]) -> None:
        if turns in seen_turns:
            return
        seen_turns.add(turns)
        scenarios.append(Scenario(f"{kind}_{len(scenarios)+1:03d}", turns, expect))

    greetings = [
        "zdravo",
        "živjo",
        "dober dan",
        "hello",
    ]
    booking_starts = [
        "rad bi termin",
        "rada bi termin",
        "rabim pregled",
        "lahko rezerviram termin",
        "rad bi se naročil",
    ]
    services = [
        "ortoped",
        "dermatolog",
        "okulist",
        "laserski poseg",
        "estetski poseg",
    ]
    services_typos = [
        "ortopet",
        "dermatalog",
        "okulsit",
        "laser",
        "botoc",
    ]
    dates = [
        "25.2.",
        "25.02.2026",
        "26.2.",
        "27.02.2026",
        "1.3.",
    ]
    times = ["08:00", "09:00", "10:30", "11:00", "12:30"]
    names = [
        "Ana Novak",
        "Marko Kralj",
        "Maja Horvat",
        "Luka Zupan",
        "Nina Vidmar",
    ]
    interrupts = [
        "kje se nahajate",
        "kakšen je delovni čas",
        "kontakt",
        "koliko stane pregled",
        "koliko je botox",
    ]

    # 1) End-to-end booking to phone step (220)
    for g, b, s, d, t, n in product(greetings, booking_starts, services, dates, times, names):
        add("BOOKING_FULL", (g, b, s, d, t, n), booking_progress_expect)
        if len(scenarios) >= 220:
            break
    
    # 2) Booking with typo services (80)
    for b, s, d, t, n in product(booking_starts, services_typos, dates, times, names):
        add("BOOKING_TYPO", (b, s, d, t, n), booking_progress_expect)
        if len([x for x in scenarios if x.scenario_id.startswith("BOOKING_TYPO")]) >= 80:
            break

    # 3) Interrupt and resume during booking (120)
    for b, s, q, d, t, n in product(booking_starts, services, interrupts, dates, times, names):
        add(
            "BOOKING_INTERRUPT",
            (b, s, q, d, t, n),
            booking_progress_expect + ("naslov", "08:00", "kontakt", "cena"),
        )
        if len([x for x in scenarios if x.scenario_id.startswith("BOOKING_INTERRUPT")]) >= 120:
            break

    # 4) Service info / typo / mixed topic (60)
    service_info_msgs = [
        "imate botox",
        "koliko je botoc",
        "koliko je filler",
        "imam madež na koži",
        "odstranjevanje bradavic",
        "zapestje sem si poškodoval",
        "imate masaše",
        "imate masaze",
        "boli me glava",
        "bradavico imam",
    ]
    followups = ["lahko", "okej", "rad bi termin", "kaj predlagate", "hvala"]
    for m1, m2 in product(service_info_msgs, followups):
        add(
            "SERVICE_MIX",
            (m1, m2),
            (
                "termin",
                "kateri datum",
                "cena",
                "ortoped",
                "dermat",
                "laserski",
                "estetski",
                "fizioterap",
                "kozmet",
                "glavobol",
                "lep dan",
                "nisem prepričan",
            ),
        )
        if len([x for x in scenarios if x.scenario_id.startswith("SERVICE_MIX")]) >= 60:
            break

    # 5) Food/general collision safety + greeting/goodbye loops (12)
    general_starts = [
        "kaj je za kosilo",
        "koleno bi jedel",
        "zdravo",
        "hello",
    ]
    general_followups = [
        ("hvala",),
        ("kontakt",),
        ("kje ste",),
    ]
    for first, rest in product(general_starts, general_followups):
        turns = (first, *rest)
        add("GENERAL_SAFE", turns, ("pomagam", "telefon", "email", "naslov", "storitve", "lep"))
        if len([x for x in scenarios if x.scenario_id.startswith("GENERAL_SAFE")]) >= 12:
            break

    # 6) Urgency / unsupported specialist (8)
    urgency_msgs = [
        "nujno potrebujem pomoč",
        "hud glavobol imam",
        "migrena me ubija",
        "imam nevrološke težave",
        "nujno",
        "urgentno",
        "zelo boli",
        "takoj pomoč",
    ]
    for turns in [(m,) for m in urgency_msgs]:
        add("URG_UNSUP", turns, ("112", "nujni", "specialist", "glavobol", "posvet", "nisem prepričan"))
        if len([x for x in scenarios if x.scenario_id.startswith("URG_UNSUP")]) >= 8:
            break

    # 7) Final mixed price/info edge cases (10)
    edge_sequences = [
        ("koliko je botox", "25.2."),
        ("koliko je filler", "rad bi termin"),
        ("koliko stane ortoped", "rad bi termin"),
        ("kje se nahajate", "rad bi termin"),
        ("kaksen je delovn cas", "rad bi termin"),
        ("kontakt", "rad bi termin"),
        ("odstranjevanje bradavic", "koliko stane"),
        ("zapestje sem si poškodoval", "lahko termin"),
        ("imam madež na koži", "25.2."),
        ("imate masaze", "koliko stane"),
        ("naročanje", "ortoped", "26.2."),
    ]
    for turns in edge_sequences:
        add(
            "EDGE_MIX",
            turns,
            ("cena", "termin", "kateri datum", "prosti termini", "telefon", "email", "naslov", "na kateri pregled"),
        )

    return scenarios[:500]


SCENARIOS = _build_500_unique_scenarios()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.scenario_id for s in SCENARIOS])
def test_e2e_500_live_like_scenarios(client: TestClient, scenario: Scenario) -> None:
    session_id = f"e2e500-{scenario.scenario_id.lower()}"

    final_reply = ""
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

        lowered = reply.lower()
        assert "internal server error" not in lowered
        assert "traceback" not in lowered
        assert "prišlo je do napake pri povezavi" not in lowered

        final_reply = lowered

    assert final_reply
    normalized = (
        final_reply.replace("š", "s")
        .replace("č", "c")
        .replace("ž", "z")
        .replace("ć", "c")
        .replace("đ", "d")
    )
    assert any(
        expected.replace("š", "s").replace("č", "c").replace("ž", "z").replace("ć", "c").replace("đ", "d")
        in normalized
        for expected in scenario.expect_any_final
    ), (
        f"Unexpected final reply for {scenario.scenario_id}: {final_reply!r}"
    )


def test_e2e_500_are_unique() -> None:
    assert len(SCENARIOS) == 500
    turns = [s.turns for s in SCENARIOS]
    assert len(set(turns)) == 500
