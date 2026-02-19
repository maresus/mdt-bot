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


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(chat_router)
    return TestClient(app)


def _build_100_ultra() -> list[Scenario]:
    greetings = [
        "zdravo",
        "živjo",
        "dobr dan",
        "hej",
        "pozdrav",
        "zivjo",
        "halo",
        "doberdan",
        "ej zdravo",
        "lep pozdrav",
    ]

    goodbyes = [
        "hvala adijo",
        "hvala, nasvidenje",
        "ok hvala lp",
        "super hvala, lep dan",
        "najlepša hvala adijo",
        "to je to, hvala",
        "hvala za pomoč, adijo",
        "ok, hvala lepa",
        "ful hvala, čau",
        "hvala in lep dan",
    ]

    flows = [
        ("rad bi termin pri dermatologu 26.02.2026 ob 11:00", "kolk stane to", "ja prosim"),
        ("bulo mam na hrbtu in peče me koža", "ajde preveri termine", "dermatolog"),
        ("kje ste pa kak delovni cas v soboto", "rad bi termin za ortopeda", "17.3.2026"),
        ("imam nevrološke težave in glavobol 3 dni", "kaj zdaj", "lahko"),
        ("rad bi prestavil termin iz 18.03.2026 na naslednji teden", "ok razumem", "kontakt prosim"),
        ("lahko dobim antibiotik brez pregleda", "ok potem termin", "okulist"),
        ("botoc + filler isti dan, kolk pride vse skp?", "termin 25.2.2026", "09:00"),
        ("a rabim napotnco za ortopeda ce mam rtg od lani", "rad bi termin", "jutri ob 9"),
        ("mate parking pa kdo je direktor", "kolko je telefonska", "koliko čakam na pregled"),
        ("need an eye exam tomorrow, can you book it?", "what is price for okulist", "book me please"),
    ]

    scenarios: list[Scenario] = []
    for fi, flow in enumerate(flows, start=1):
        for gi, greeting in enumerate(greetings, start=1):
            goodbye = goodbyes[(gi + fi) % len(goodbyes)]
            scenarios.append(
                Scenario(
                    scenario_id=f"ULTRA_{fi:02d}_{gi:02d}",
                    turns=(greeting, *flow, goodbye),
                )
            )
    return scenarios


SCENARIOS = _build_100_ultra()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.scenario_id for s in SCENARIOS])
def test_e2e_100_ultra_variants(client: TestClient, scenario: Scenario) -> None:
    session_id = f"e2e-ultra-{scenario.scenario_id.lower()}"

    final_reply = ""
    replies: list[str] = []
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

        replies.append(lowered)
        final_reply = lowered

    assert replies
    assert any(
        token in "\n".join(replies)
        for token in (
            "dermatolog",
            "ortoped",
            "okulist",
            "prosti termini",
            "kateri datum",
            "katera ura",
            "pregled",
            "termin",
            "telefon",
            "park",
            "cena",
            "zdravnik",
        )
    ), f"Conversation had no clinically-relevant routing signal: {scenario.scenario_id}"

    assert final_reply
    assert any(
        expected in final_reply
        for expected in (
            "hvala za zaupanje",
            "lep dan",
            "nasvidenje",
            "nadaljujemo z naročilom",
            "na kateri pregled",
            "kateri datum",
            "katera ura",
            "pokličite",
            "izberite specialista",
            "kako vam lahko pomagam",
            "datum",
            "termin",
        )
    ), f"Unexpected final reply for {scenario.scenario_id}: {final_reply!r}"
