from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.services.chat_router as chat_router_module
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
            "FLOW_SERVICE_TYPO_DERMATOLOGO",
            ("rad bi se naročil", "dermatologo", "12.3.2026"),
            ("prosti termini", "katera ura", "termin 12.03.2026"),
        ),
        Scenario(
            "FLOW_BOOKING_WITH_DATE",
            ("rad bi termin", "dermatolog", "24.3.2026"),
            ("prosti termini", "izberite drug datum"),
        ),
        Scenario(
            "FLOW_BOOKING_ONE_SHOT_SERVICE_DATE_TIME",
            ("rad bi termin pri dermatologu 26.02 ob 11",),
            ("prosti termini", "termin 26.02", "izberite drug datum"),
        ),
        Scenario(
            "FLOW_DATE_AFTER_SERVICE_INFO",
            ("dermatologo", "12.3.2026"),
            ("prosti termini", "katera ura", "termin 12.03.2026"),
        ),
        Scenario(
            "FLOW_DATE_AFTER_SERVICE_INFO_SHORT_DATE",
            ("dermatologo", "15.3"),
            ("prosti termini", "katera ura", "izberite drug datum"),
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
            "FLOW_PRICE_DURING_NAME_AND_SERVICE_FOLLOWUP",
            ("rad bi termin", "dermatolo", "27.3.2026", "08:30", "koliko stane pregled", "dermatolog"),
            ("cena", "25", "150", "nadaljujemo z naročilom"),
        ),
        Scenario(
            "FLOW_SYMPTOM_DURING_PHONE_STEP",
            ("rad bi termin", "dermatolog", "27.3.2026", "08:00", "Marko Satler", "boli me glava"),
            ("glavobol", "nadaljujemo z naročilom", "telefonsko"),
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
            "INFO_PARKING_SLANG",
            ("mate parkirni prostor",),
            ("park", "naslov", "lokacij"),
        ),
        Scenario(
            "INFO_WAITING_TIME",
            ("koliko čakam",),
            ("čakalna", "cakalna", "odvisna od storitve", "prvi prost termin"),
        ),
        Scenario(
            "FLOW_NO_LOOP_ON_SYMPTOM_REPEAT",
            ("imam bradavico", "bradavico imam"),
            ("laserski poseg", "bradavice", "preverim prost termin"),
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
            "INFO_MEDICATION_QUESTION",
            ("lahko pri vas dobim kake tablete?",),
            ("ne izdajamo zdravil", "potreben posvet", "naročim na ustrezen pregled"),
        ),
        Scenario(
            "INFO_PREVISIT_DOCUMENTS",
            ("Ali potrebujem izvide pred pregledom kolena?",),
            ("prinesete obstoječe izvide", "seznam zdravil", "preverim prost termin"),
        ),
        Scenario(
            "INFO_PREVISIT_DOCUMENTS_TYPOS",
            ("A rabim napotnco za ortopeda, mam sam RTG od lani?",),
            ("prinesete obstoječe izvide", "napotnico", "preverim prost termin"),
        ),
        Scenario(
            "INFO_PREVISIT_DOCUMENTS_DERMATOLOG",
            ("kaj vse rabim s sabo za dermatologa",),
            ("prinesete obstoječe izvide", "seznam zdravil", "preverim prost termin"),
        ),
        Scenario(
            "INTERRUPT_URGENCY_CHEST",
            ("bolečina v prsih + težko diham, a mate jutri termin?",),
            ("112", "nujni primer", "prednostne termine"),
        ),
        Scenario(
            "SERVICE_INFO_AESTHETIC_PRICE",
            ("botoc + filler isti dan, kolk pride vse skp?",),
            ("estetski", "botox", "filler", "80-300"),
        ),
        Scenario(
            "INTERRUPT_SYMPTOM_HEADACHE",
            ("boli me glava",),
            ("glavobol", "zdravnikom", "nujno obravnavo", "splošni posvet", "proste termine", "kako vam lahko pomagam"),
        ),
        Scenario(
            "INTERRUPT_SYMPTOM_HEADACHE_VARIANT",
            ("glava me boli že 3 dni",),
            ("glavobol", "zdravnikom", "poslabša", "proste termine"),
        ),
        Scenario(
            "INTERRUPT_SYMPTOM_SKIN",
            ("imam srbec izpuscaj",),
            ("dermatolo", "kož", "kako vam lahko pomagam"),
        ),
        Scenario(
            "TRIAGE_SYMPTOM_UNKNOWN",
            ("bulo imam na hrbtu",),
            ("osebnim zdravnikom", "to ni zdravniška diagnoza", "ustreznemu specialistu"),
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
            "INFO_LOCATION_AND_HOURS_COMBINED",
            ("Kje ste in kakšen je delovni čas v soboto?",),
            ("naslov", "delovni čas", "sobota"),
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
        Scenario(
            "LOOP_UNCERTAIN_HELP_SOFT",
            ("zdravo, ne vem točno kaj rabim, sam neki ni ok", "zdravo, ne vem točno kaj rabim, sam neki ni ok"),
            ("kako vam lahko pomagam", "kaj vas danes zanima", "povejte"),
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


def test_booking_recovers_when_step_missing_mid_flow(client: TestClient) -> None:
    session_id = "e2e-step-recovery"
    clinic_id = "test_center"

    for msg in ("rad bi se naročil", "okulist", "18.3.2026"):
        response = client.post(
            "/chat/",
            json={"message": msg, "session_id": session_id, "clinic_id": clinic_id},
        )
        assert response.status_code == 200

    internal_session_id = f"{clinic_id}::{session_id}"
    state = chat_router_module.get_appointment_state(internal_session_id)
    state["step"] = None

    response = client.post(
        "/chat/",
        json={"message": "12:00", "session_id": session_id, "clinic_id": clinic_id},
    )
    assert response.status_code == 200
    reply = str(response.json().get("reply", "")).lower()
    assert "na kateri pregled se želite naročiti" not in reply
    assert ("termin 18.03.2026 ob 12:00 je prost" in reply) or ("prosim izberite drug termin" in reply)


def test_booking_recovers_after_legacy_state_cold_start(client: TestClient) -> None:
    session_id = "e2e-legacy-cold-start-recover"
    clinic_id = "test_center"

    for msg in ("rad bi se naročil", "dermatolog", "18.3.2026"):
        response = client.post(
            "/chat/",
            json={"message": msg, "session_id": session_id, "clinic_id": clinic_id},
        )
        assert response.status_code == 200

    # Simulate deploy/restart: legacy in-memory state wiped, unified state remains.
    chat_router_module.appointment_states.clear()

    response = client.post(
        "/chat/",
        json={"message": "08:00", "session_id": session_id, "clinic_id": clinic_id},
    )
    assert response.status_code == 200
    reply = str(response.json().get("reply", "")).lower()
    assert "na kateri pregled se želite naročiti" not in reply
    assert ("termin 18.03.2026 ob 08:00 je prost" in reply) or ("prosim izberite drug termin" in reply)
