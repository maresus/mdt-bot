from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.chat_router import router as chat_router


@dataclass(frozen=True)
class Step:
    session_id: str
    message: str
    expect_any: tuple[str, ...] = ()


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(chat_router)
    return TestClient(app)


def _conversation_1() -> list[Step]:
    # Booking + topic switch + resume + confirmation
    return [
        Step("e2e-s1", "zdravo", ("pomagam", "zanima")),
        Step("e2e-s1", "rad bi se narocil", ("na kateri pregled", "kateri datum")),
        Step("e2e-s1", "ortoped", ("ortopedija", "kateri datum", "prosti termini")),
        Step("e2e-s1", "kje ste", ("naslov", "parkiranje", "kako vam lahko pomagam")),
        Step("e2e-s1", "23.3.2026", ("prosti termini", "izberite drug datum")),
        Step("e2e-s1", "12:00", ("ime in priimek", "prosim povejte uro")),
        Step("e2e-s1", "Marko Satler", ("telefonska", "telefonsko")),
        Step("e2e-s1", "041444444", ("email", "e-po")),
        Step("e2e-s1", "satlermarko@gmail.com", ("razlog",)),
        Step("e2e-s1", "bolecina v kolenu", ("ali so podatki pravilni",)),
        Step("e2e-s1", "DA", ("naročilo uspešno", "nadaljujemo z naročilom")),
        Step("e2e-s1", "hvala", ("hvala", "lep dan", "pomagam")),
    ]


def _conversation_2() -> list[Step]:
    # Slang + typo + repeated switches while booking
    return [
        Step("e2e-s2", "ej zivjo", ("pomagam", "zanima")),
        Step("e2e-s2", "narocu bi se", ("na kateri pregled", "kateri datum")),
        Step("e2e-s2", "dermatolog", ("dermatologija", "kateri datum", "prosti termini")),
        Step("e2e-s2", "kaki mate cene", ("cene", "storitve")),
        Step("e2e-s2", "25.3.2026", ("prosti termini", "izberite drug datum")),
        Step("e2e-s2", "10:30", ("ime in priimek", "prosim povejte uro")),
        Step("e2e-s2", "Miha Novak", ("telefonska", "telefonsko")),
        Step("e2e-s2", "031123123", ("email", "e-po")),
        Step("e2e-s2", "ne", ("razlog", "brez e-pošte", "potrditev po e-pošti", "email")),
        Step("e2e-s2", "srbec izpuscaj", ("ali so podatki pravilni", "dermatološki", "potrditev po e-pošti", "email")),
        Step("e2e-s2", "NE", ("prosim popravite", "preklicano", "na kateri pregled", "kateri datum", "potrditev po e-pošti", "email")),
        Step("e2e-s2", "okulist", ("okul", "kateri datum", "prosti termini")),
    ]


def _conversation_3() -> list[Step]:
    # Info-heavy user with typos and slang
    return [
        Step("e2e-s3", "kje se nahajaet", ("naslov", "parkiranje")),
        Step("e2e-s3", "kaksn delovn cas", ("ponedeljka", "08:00", "delamo")),
        Step("e2e-s3", "kolk stane ortoped", ("cena", "40", "80")),
        Step("e2e-s3", "kdo je direktor", ("vodstvu", "uradno informacijo", "recepcijo")),
        Step("e2e-s3", "maste parking", ("parkiranje", "parkiri", "kako vam lahko pomagam")),
        Step("e2e-s3", "kontakt pls", ("telefon", "email")),
        Step("e2e-s3", "prosti termini", ("prosti", "termin", "na kateri pregled")),
        Step("e2e-s3", "nujno je", ("112", "nujni primer", "na kateri pregled")),
        Step("e2e-s3", "boli me glava", ("nevrologa", "splošni posvet", "proste termine", "kako vam lahko pomagam")),
        Step("e2e-s3", "da", ("pomagam", "naročilom", "storitvah", "lokacijo", "na kateri pregled")),
        Step("e2e-s3", "ok hvala", ("hvala", "lep dan", "pomagam", "na kateri pregled")),
        Step("e2e-s3", "kje ste", ("naslov", "parkiranje", "kako vam lahko pomagam")),
    ]


def _conversation_4() -> list[Step]:
    # Repeats + loop pressure + flow recovery
    return [
        Step("e2e-s4", "zdravo", ("pomagam", "zanima")),
        Step("e2e-s4", "zdravo", ("pomagam", "ponavljanje", "nesporazuma")),
        Step("e2e-s4", "zdravo", ("pomagam", "ponavljanje", "nesporazuma")),
        Step("e2e-s4", "rad bi termin", ("na kateri pregled", "kateri datum")),
        Step("e2e-s4", "ortoped", ("ortopedija", "kateri datum", "prosti termini")),
        Step("e2e-s4", "ortoped", ("kateri datum", "prosti termini", "ponavljanje", "ortopedija")),
        Step("e2e-s4", "26.3.2026", ("prosti termini", "izberite drug datum")),
        Step("e2e-s4", "08:00", ("ime in priimek", "prosim povejte uro")),
        Step("e2e-s4", "Ana Kralj", ("telefonska", "telefonsko")),
        Step("e2e-s4", "040111222", ("email", "e-po")),
        Step("e2e-s4", "ana@example.com", ("razlog",)),
        Step("e2e-s4", "bolečina v hrbtu", ("ali so podatki pravilni",)),
        Step("e2e-s4", "DA", ("naročilo uspešno", "nadaljujemo z naročilom")),
    ]


def _extra_noise() -> list[Step]:
    # 51 extra one-shot turns to reach exactly 100 turns total.
    pool = [
        ("e2e-n1", "kje ste"),
        ("e2e-n2", "kaksen je kontakt"),
        ("e2e-n3", "kolk stane pregled"),
        ("e2e-n4", "ortoped"),
        ("e2e-n5", "kdo vodi podjetje"),
        ("e2e-n6", "hvala"),
        ("e2e-n7", "nujno"),
        ("e2e-n8", "prosti termini"),
        ("e2e-n9", "zdravo"),
    ]
    steps: list[Step] = []
    idx = 0
    while len(steps) < 51:
        sid, msg = pool[idx % len(pool)]
        steps.append(Step(f"{sid}-{idx}", msg))
        idx += 1
    return steps


def test_e2e_100_complex_chat_scenarios() -> None:
    client = _build_client()

    scenarios = _conversation_1() + _conversation_2() + _conversation_3() + _conversation_4() + _extra_noise()
    assert len(scenarios) == 100

    for step in scenarios:
        response = client.post(
            "/chat/",
            json={
                "message": step.message,
                "session_id": step.session_id,
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

        if step.expect_any:
            assert any(expected in lowered for expected in step.expect_any), (
                f"Unexpected reply for message={step.message!r}, reply={reply!r}"
            )
