from __future__ import annotations

from dataclasses import dataclass

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


def _base_scenarios() -> list[Scenario]:
    return [
        Scenario("BOOKING_ORTHO_FULL", ("rad bi termin", "ortoped", "25.2.", "09:00", "Ana Novak"), ("telefonska", "telefonsko")),
        Scenario("BOOKING_DERMA_FULL", ("rad bi termin", "dermatolog", "26.2.", "10:00", "Marko Novak"), ("telefonska", "telefonsko")),
        Scenario("BOOKING_OKU_FULL", ("rad bi termin", "okulist", "27.2.", "11:00", "Maja Novak"), ("telefonska", "telefonsko")),
        Scenario("PRICE_BOTOX_TYPO", ("koliko je botoc",), ("cena", "estetski", "80", "300")),
        Scenario("PRICE_FILLER", ("koliko je filler",), ("cena", "estetski", "80", "300")),
        Scenario("PRICE_BRADAVICA", ("koliko je poseg za bradavico",), ("cena", "laserski", "50", "200")),
        Scenario("SERVICE_MASAZE", ("imate masaše",), ("fizioterap", "masaže", "kozmet", "tretma", "storitve")),
        Scenario("SYMPTOM_WRIST", ("zapestje sem si poškodoval",), ("ortoped", "pregled", "termin")),
        Scenario("SYMPTOM_WRIST_BOOK", ("pregled bi rad za boleče zapestje",), ("ortoped", "kateri datum", "prosti termini")),
        Scenario("SYMPTOM_BRADAVICA_BOOK", ("bradavico imam", "da", "laserski poseg"), ("kateri datum", "prosim v formatu")),
        Scenario("INTERRUPT_LOCATION_RESUME", ("rad bi termin", "ortoped", "kje ste", "25.2."), ("prosti termini", "izberite drug datum")),
        Scenario("INTERRUPT_PRICE_RESUME", ("rad bi termin", "dermatolog", "koliko je botox", "25.2."), ("prosti termini", "izberite drug datum", "cena")),
        Scenario("FASTPASS_LOCATION", ("kje se nahajate",), ("naslov", "parkiranje")),
        Scenario("FASTPASS_HOURS", ("kakšen je delovni čas",), ("08:00", "18:00", "ponedeljka")),
        Scenario("FASTPASS_CONTACT", ("kontakt",), ("telefon", "email")),
        Scenario("PRICE_GENERIC", ("koliko stane pregled",), ("storitev", "cene")),
        Scenario("PRICE_SERVICE", ("koliko stane ortoped",), ("cena", "40", "80")),
        Scenario("HEADACHE_UNSUPPORTED", ("boli me glava",), ("glavobol", "specialist", "možnosti", "moznosti")),
        Scenario("URGENT_CASE", ("nujno potrebujem pomoč",), ("112", "nujni", "urgent")),
        Scenario("GREET_THANKS", ("zdravo", "hvala"), ("lep dan", "pomagam")),
        Scenario("DATE_SHORT_FORMAT", ("rad bi termin", "ortoped", "25.2."), ("prosti termini", "izberite drug datum")),
        Scenario("DATE_LONG_FORMAT", ("rad bi termin", "ortoped", "25.02.2026"), ("prosti termini", "izberite drug datum")),
        Scenario("SERVICE_INFO_BOTOX", ("imate botox",), ("estetski", "botox", "termin")),
        Scenario("SERVICE_INFO_BRADAVICE", ("imate odstranjevanje bradavic",), ("laserski", "bradavic", "termin")),
        Scenario("NO_FOOD_COLLISION", ("kaj je za kosilo",), ("pomagam", "storitve", "naročilom", "telefon", "email")),
    ]


def _build_500() -> list[Scenario]:
    base = _base_scenarios()
    scenarios: list[Scenario] = []
    batch = 1
    while len(scenarios) < 500:
        for item in base:
            if len(scenarios) >= 500:
                break
            scenarios.append(
                Scenario(
                    scenario_id=f"{item.scenario_id}_{batch:03d}",
                    turns=item.turns,
                    expect_any_final=item.expect_any_final,
                )
            )
        batch += 1
    return scenarios


SCENARIOS = _build_500()


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
    assert any(expected in final_reply for expected in scenario.expect_any_final), (
        f"Unexpected final reply for {scenario.scenario_id}: {final_reply!r}"
    )
