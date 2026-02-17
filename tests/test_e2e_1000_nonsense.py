from __future__ import annotations

from itertools import product

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.chat_router import router as chat_router


def _build_1000_nonsense_messages() -> list[str]:
    prefixes = [
        "zdravo ???",
        "aaaa",
        "neki neki",
        "mhm",
        "ej",
        "halo",
        "yo",
        "xx",
        "random",
        "hmm",
        "kaj pa ce",
        "ce recem",
        "imam xyz",
        "tole",
        "bmk",
        "test",
        "nwm",
        "wtf",
        "abc",
        "lol",
    ]
    middles = [
        "koleno oko koza",
        "123 456",
        "??!!",
        "jutri 25.2.",
        "botoc filler laser",
        "a loh",
        "nimam pojma",
        "prosim termin",
        "rabim neki",
        "bula glava nos",
        "parking lokacija",
        "koliko stane ce ne vem",
        "napotnca rtg mr",
        "krvavim ali ne",
        "zdj takoj",
        "madez srbi",
        "zapestje boli",
        "slabo vidim",
        "kdo je direktor",
        "tablete brez pregleda",
        "26.02 ob 11",
        "hvala adijo",
        "ne vem tocno",
        "aaaa bbbb cccc",
        "x y z",
    ]
    suffixes = [" ???", " pls"]
    messages = [f"{p} {m}{s}" for p, m, s in product(prefixes, middles, suffixes)]
    assert len(messages) == 1000
    return messages


NONSENSE_MESSAGES = _build_1000_nonsense_messages()


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(chat_router)
    return TestClient(app)


@pytest.mark.parametrize("message", NONSENSE_MESSAGES)
def test_1000_nonsense_messages_do_not_crash(client: TestClient, message: str) -> None:
    response = client.post(
        "/chat/",
        json={
            "message": message,
            "session_id": f"nonsense::{abs(hash(message))}",
            "clinic_id": "test_center",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    reply = str(payload.get("reply") or "")
    assert reply.strip() != ""
    lowered = reply.lower()
    assert "traceback" not in lowered
    assert "internal server error" not in lowered
