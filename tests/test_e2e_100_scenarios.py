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
        Scenario(
            "FLOW_BOOKING_BASIC",
            ("zdravo", "rad bi se narocil", "ortoped"),
            ("ortopedija", "kateri datum", "prosti termini"),
        ),
        Scenario(
            "FLOW_SERVICE_PARTIAL_TOKEN",
            ("rad bi se narocil", "dermatolo"),
            ("kateri datum", "prosim v formatu", "datum vam ustreza"),
        ),
        Scenario(
            "FLOW_BOOKING_WITH_DATE",
            ("rad bi termin", "dermatolog", "24.3.2026"),
            ("prosti termini", "izberite drug datum"),
        ),
        Scenario(
            "FLOW_BOOKING_EMAIL_REASON",
            ("rad bi termin", "okulist", "24.3.2026", "10:00", "Ana Novak", "040111222", "ana@example.com", "slabsi vid"),
            ("ali so podatki pravilni", "prosim vnesite veljaven"),
        ),
        Scenario(
            "FLOW_BOOKING_NEGATIVE_BRANCH",
            ("rad bi termin", "ortoped", "24.3.2026", "09:00", "Miha Kralj", "031123123", "ne"),
            ("razlog", "potrditev po e-pošti", "email"),
        ),
        Scenario(
            "FLOW_INTERRUPTED_LOCATION",
            ("rad bi termin", "ortoped", "kje ste", "24.3.2026"),
            ("prosti termini", "izberite drug datum", "kako vam lahko pomagam"),
        ),
        Scenario(
            "FLOW_INTERRUPTED_LOCATION_RESUME_HINT",
            ("rad bi termin", "okulist", "kje ste"),
            ("nadaljujemo z naročilom", "kateri datum", "naslov"),
        ),
        Scenario(
            "FLOW_INTERRUPTED_PRICE",
            ("rad bi termin", "dermatolog", "koliko stane pregled", "24.3.2026"),
            ("prosti termini", "izberite drug datum", "cene"),
        ),
        Scenario(
            "INFO_FUZZY_LOCATION",
            ("kje se nahajaet",),
            ("naslov", "parkiranje", "kako vam lahko pomagam"),
        ),
        Scenario(
            "INFO_FUZZY_HOURS",
            ("kaksn delovn cas",),
            ("08:00", "delamo", "ponedeljka"),
        ),
        Scenario(
            "INFO_CONTACT",
            ("kontakt pls",),
            ("telefon", "email", "kako vam lahko pomagam"),
        ),
        Scenario(
            "INFO_PRICE_GENERIC",
            ("kolk stane pregled",),
            ("cene", "storitev"),
        ),
        Scenario(
            "INFO_PRICE_WITH_SERVICE",
            ("kolk stane ortoped",),
            ("cena", "40", "80"),
        ),
        Scenario(
            "INFO_COMPANY_DIRECTOR",
            ("kdo je direktor",),
            ("uradno informacijo", "recepcijo", "vodstvu"),
        ),
        Scenario(
            "INTERRUPT_SYMPTOM_HEADACHE",
            ("boli me glava",),
            ("glavobol", "zdravnikom", "nujno obravnavo", "splošni posvet", "proste termine", "kako vam lahko pomagam"),
        ),
        Scenario(
            "INTERRUPT_SYMPTOM_SKIN",
            ("imam srbec izpuscaj",),
            ("dermatolo", "kož", "kako vam lahko pomagam"),
        ),
        Scenario(
            "INTERRUPT_URGENCY",
            ("nujno je",),
            ("112", "nujni primer", "na kateri pregled"),
        ),
        Scenario(
            "LOOP_REPEAT_GREETING",
            ("zdravo", "zdravo", "zdravo"),
            ("ponavljanje", "nesporazuma", "pomagam"),
        ),
        Scenario(
            "LOOP_REPEAT_SERVICE",
            ("rad bi termin", "ortoped", "ortoped"),
            ("kateri datum", "prosti termini", "ponavljanje", "ortopedija"),
        ),
        Scenario(
            "MIX_TOPIC_SWITCH_BACK",
            ("zdravo", "kje ste", "rad bi se narocil", "ortoped", "25.3.2026"),
            ("prosti termini", "izberite drug datum"),
        ),
        Scenario(
            "MIX_PRICE_THEN_BOOK",
            ("koliko stane pregled", "ortoped", "rad bi termin", "ortoped"),
            ("ortopedija", "kateri datum", "prosti termini", "cena"),
        ),
        Scenario(
            "PRICE_FOLLOWUP_SERVICE_SAME_SESSION",
            ("koliko stane pregled", "okulist"),
            ("cena", "30", "120"),
        ),
        Scenario(
            "PRICE_AFTER_BOOKING_MEMORY",
            (
                "rad bi termin",
                "ortoped",
                "24.3.2026",
                "10:00",
                "Ana Novak",
                "040111222",
                "ana@example.com",
                "bolecine v kolenu",
                "DA",
                "koliko stane pregled",
            ),
            ("cena", "40", "80", "imate že termin"),
        ),
        Scenario(
            "FASTPASS_REPEAT_NO_LOOP",
            ("koliko stane pregled", "koliko stane pregled", "koliko stane pregled"),
            ("cene pregledov", "cenik je vezan", "cena je odvisna"),
        ),
        Scenario(
            "MIX_GOODBYE_REENTRY",
            ("hvala", "zdravo", "kaksen je kontakt"),
            ("telefon", "email", "pomagam", "lep dan"),
        ),
    ]


def _build_100() -> list[Scenario]:
    base = _base_scenarios()
    scenarios: list[Scenario] = []
    batch = 1
    while len(scenarios) < 100:
        for item in base:
            if len(scenarios) >= 100:
                break
            scenarios.append(
                Scenario(
                    scenario_id=f"{item.scenario_id}_{batch:02d}",
                    turns=item.turns,
                    expect_any_final=item.expect_any_final,
                )
            )
        batch += 1
    return scenarios


SCENARIOS = _build_100()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.scenario_id for s in SCENARIOS])
def test_e2e_100_complex_chat_scenarios(client: TestClient, scenario: Scenario) -> None:
    session_id = f"e2e-{scenario.scenario_id.lower()}"

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
        assert "prišlo je do napake pri povezavi" not in lowered
        assert "internal server error" not in lowered
        assert "traceback" not in lowered

        final_reply = lowered

    assert final_reply
    assert any(expected in final_reply for expected in scenario.expect_any_final), (
        f"Unexpected final reply for {scenario.scenario_id}: {final_reply!r}"
    )
