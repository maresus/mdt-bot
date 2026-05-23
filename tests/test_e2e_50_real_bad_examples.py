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
    must_include_any: tuple[str, ...]


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(chat_router)
    return TestClient(app)


SCENARIOS: list[Scenario] = [
    Scenario("BAD_001_PARKING", ("mate parkirni prostor",), ("park", "naslov", "lokacij")),
    Scenario("BAD_002_WAITING", ("koliko čakam",), ("čakal", "cakal", "odvisna od storitve", "prvi prost termin")),
    Scenario("BAD_003_WAITING_DERM", ("kolk cakam za dermatologa",), ("čakal", "dermatolog", "termin")),
    Scenario("BAD_004_BUMP", ("bulo mam",), ("osebnim zdravnikom", "to ni zdravniška diagnoza", "specialist")),
    Scenario("BAD_005_BUMP_BACK", ("bulo imam na hrbtu",), ("osebnim zdravnikom", "to ni zdravniška diagnoza", "specialist")),
    Scenario("BAD_006_HEADACHE", ("glava me boli",), ("glavobol", "zdravnikom", "specialist")),
    Scenario("BAD_007_HEADACHE_3D", ("glava me boli 3 dni",), ("glavobol", "zdravnikom", "specialist")),
    Scenario("BAD_008_CHEST_PAIN", ("bolečina v prsih in težko diham",), ("112", "nujni", "urgent")),
    Scenario("BAD_009_MEDS", ("lahko dobim antibiotik brez pregleda",), ("ne izdajamo zdravil", "posvet", "zdravnik")),
    Scenario("BAD_010_PILLS", ("lahko pri vas dobim kake tablete",), ("ne izdajamo zdravil", "posvet", "zdravnik")),

    Scenario("BAD_011_BOTOX_PRICE", ("koliko je botox",), ("estetski", "botox", "80-300")),
    Scenario("BAD_012_FILLER_PRICE", ("koliko je filler",), ("estetski", "filler", "80-300")),
    Scenario("BAD_013_BOTOX_FILLER", ("botoc + filler isti dan, kolk pride vse skp",), ("estetski", "botox", "filler")),
    Scenario("BAD_014_WART_REMOVAL", ("imate odstranjevanje bradavic",), ("laserski", "bradavic", "50-200")),
    Scenario("BAD_015_WART_PRICE", ("koliko je poseg za bradavico",), ("laserski", "bradavic", "50-200")),
    Scenario("BAD_016_SKIN_BURN", ("neki me peče po koži, mogoče alergija mogoče glivice",), ("dermatolo", "kož", "pregled")),
    Scenario("BAD_017_WRIST_INJURY", ("zapestje sem si poškodoval",), ("ortoped", "pregled", "sklepi")),
    Scenario("BAD_018_KNEE_DOCS", ("A rabim napotnco za ortopeda al ne, pa če mam sam RTG od lani",), ("izvide", "napotnico", "ortoped")),
    Scenario("BAD_019_DERM_DOCS", ("kaj vse rabim s sabo za dermatologa",), ("izvide", "seznam zdravil", "dermatolog")),
    Scenario("BAD_020_EYE_DOCS", ("kaj rabim s sabo za okulista",), ("izvide", "okulist", "osebni dokument")),

    Scenario("BAD_021_CONTACT_PHONE", ("koliko je telefonska",), ("telefon", "email")),
    Scenario("BAD_022_LOCATION_HOURS", ("Kje ste in kakšen je delovni čas v soboto",), ("naslov", "delovni čas", "sobota")),
    Scenario("BAD_023_DIRECTOR", ("kdo je direktor",), ("uradno informacijo", "recepcijo", "vodstvu")),
    Scenario("BAD_024_SMALL_DATE", ("25.2.",), ("brez ugibanja", "želite informacijo", "za kateri datum")),
    Scenario("BAD_025_VAGUE_HELP", ("zdravo, ne vem točno kaj rabim, sam neki ni ok",), ("kako vam lahko pomagam", "kaj vas danes zanima", "povejte")),
    Scenario("BAD_026_REPEAT_VAGUE", ("zdravo, ne vem točno kaj rabim", "zdravo, ne vem točno kaj rabim"), ("ponavljanje", "kako vam lahko pomagam", "kaj vas zanima")),
    Scenario("BAD_027_RESCHEDULE", ("Rad bi prestavil termin iz 18.03.2026 na naslednji teden",), ("prestavitev termina trenutno ni možna preko klepeta", "pokličite", "01 234 56 78")),
    Scenario("BAD_028_RESCHEDULE_SHORT", ("prestavim termin",), ("prestavitev", "pokličite", "telefon")),
    Scenario("BAD_029_NEURO", ("imam nevrološke težave",), ("osebnim zdravnikom", "to ni zdravniška diagnoza", "specialist")),
    Scenario("BAD_030_MASSAGE", ("imate masaže",), ("fizioterapija", "masaže", "povejte mi datum")),

    Scenario("BAD_031_BOOK_TYPO_SERVICE", ("rad bi se naročil", "dermatologo", "12.3.2026"), ("prosti termini", "katera ura", "12.03.2026")),
    Scenario("BAD_032_BOOK_SHORT_DATE", ("rad bi termin", "dermatolog", "15.3"), ("prosti termini", "katera ura", "datum")),
    Scenario("BAD_033_BOOK_ONE_LINE", ("rad bi termin pri ortopedu jutri ob 9",), ("prosti termini", "ortoped", "katera ura")),
    Scenario("BAD_034_BOOK_ONE_LINE_DERM", ("rad bi termin pri dermatologu 26.02 ob 11",), ("prosti termini", "dermatolog", "katera ura")),
    Scenario("BAD_035_BOOK_SWITCH_TOPIC", ("rad bi termin", "ortoped", "kje ste", "24.3.2026"), ("prosti termini", "naslov", "datum")),
    Scenario("BAD_036_BOOK_PRICE_INTERRUPT", ("rad bi termin", "dermatolog", "koliko stane pregled", "24.3.2026"), ("cena", "prosti termini", "datum")),
    Scenario("BAD_037_BOOK_SYMPTOM_INTERRUPT", ("rad bi termin", "dermatolog", "imam bradavico", "26.3.2026"), ("bradavic", "prosti termini", "datum")),
    Scenario("BAD_038_BOOK_ENGLISH", ("need an eye exam tomorrow",), ("okulist", "kateri datum", "termin")),
    Scenario("BAD_039_BOOK_ENGLISH_MIX", ("book me dermatologist on 12.3.2026",), ("dermatolog", "prosti termini", "datum")),
    Scenario("BAD_040_CONFIRM_FLOW", ("rad bi termin", "okulist", "18.3.2026", "09:00", "Marko Satler", "041111111", "marko@test.si", "slab vid", "da"), ("naročilo prejeto", "potrditev", "termin")),

    Scenario("BAD_041_GREETING_ONLY", ("zdravo",), ("pozdrav", "kako vam lahko pomagam", "kaj vas zanima")),
    Scenario("BAD_042_GREETING_SLANG", ("ej",), ("pozdrav", "kako vam lahko pomagam", "kaj vas zanima")),
    Scenario("BAD_043_UNCLEAR", ("kaj zdaj",), ("da vas pravilno usmerim", "ali želite informacijo ali termin", "za katero storitev")),
    Scenario("BAD_044_AFFIRM_ONLY", ("lahko",), ("da vas pravilno usmerim", "ali želite informacijo ali termin", "za katero storitev")),
    Scenario("BAD_045_TOPIC_MIX", ("mate parking pa kdo je direktor pa kolko čakam",), ("park", "vodstvu", "čakal")),
    Scenario("BAD_046_NEG_TYPO", ("koleno bi jedel",), ("ortoped", "kolen", "pregled")),
    Scenario("BAD_047_DERM_SLANG", ("bradavico mam",), ("laserski", "bradavic", "termin")),
    Scenario("BAD_048_CONTACT_THEN_BOOK", ("kontakt", "rad bi termin", "okulist"), ("telefon", "email", "kateri datum")),
    Scenario("BAD_049_PRICE_GENERIC", ("kolk stane pregled",), ("cene", "za katero storitev", "storitev")),
    Scenario("BAD_050_PRICE_THEN_SERVICE", ("kolk stane pregled", "ortoped"), ("40-80", "ortoped", "cena")),
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.scenario_id for s in SCENARIOS])
def test_e2e_50_real_bad_examples(client: TestClient, scenario: Scenario) -> None:
    session_id = f"e2e-real-bad-{scenario.scenario_id.lower()}"
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

        lowered = reply.lower()
        assert "internal server error" not in lowered
        assert "traceback" not in lowered
        assert "prišlo je do napake pri povezavi" not in lowered

        transcript.append(lowered)

    merged = "\n".join(transcript)
    assert any(token in merged for token in scenario.must_include_any), (
        f"Scenario {scenario.scenario_id} missing expected behavior. Transcript:\n{merged}"
    )
