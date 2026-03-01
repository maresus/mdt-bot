from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.chat_router import router as chat_router


def _client() -> TestClient:
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


def test_waiting_time_question_does_not_jump_to_service_picker() -> None:
    client = _client()
    res = client.post(
        "/chat/",
        json={"message": "kak dolgo cakamo na pregled", "session_id": "wait-1", "clinic_id": "test_center"},
    )
    assert res.status_code == 200
    reply = _norm(res.json().get("reply", ""))
    assert "cakalna doba" in reply or "cakalna" in reply
    assert "na kateri pregled se zelite narociti" not in reply
    assert "izberite storitev" not in reply


def test_provider_question_with_service_stays_info_not_booking() -> None:
    client = _client()
    res = client.post(
        "/chat/",
        json={
            "message": "kdo opravlja dermatoloski pregled",
            "session_id": "provider-1",
            "clinic_id": "test_center",
        },
    )
    assert res.status_code == 200
    reply = _norm(res.json().get("reply", ""))
    assert "dermatoloski pregled" in reply
    assert "dermatolog" in reply
    assert "trajanje pregleda" in reply
    assert "cena" in reply
    assert "kateri datum" not in reply


def test_greeting_variants_rotate_for_test_center() -> None:
    client = _client()
    r1 = client.post("/chat/", json={"message": "zdravo", "session_id": "greet-a", "clinic_id": "test_center"})
    r2 = client.post("/chat/", json={"message": "zdravo", "session_id": "greet-b", "clinic_id": "test_center"})
    assert r1.status_code == 200 and r2.status_code == 200
    t1 = r1.json().get("reply", "").strip()
    t2 = r2.json().get("reply", "").strip()
    assert t1
    assert t2
    assert t1 != t2

