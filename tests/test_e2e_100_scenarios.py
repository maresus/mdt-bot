from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.chat_router import router as chat_router


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(chat_router)
    return TestClient(app)


def test_e2e_100_chat_scenarios() -> None:
    client = _build_client()

    multi_turn_flow = [
        "zdravo",
        "rad bi se narocil",
        "ortoped",
        "23.3.2026",
        "12:00",
        "Marko Satler",
        "041444444",
        "satlermarko@gmail.com",
        "bolecina v kolenu",
        "DA",
        "kje se nahajate",
        "koliko stane pregled",
    ]

    single_turn_pool = [
        "kaksen je delovni cas",
        "kaksen je kontakt",
        "kje ste",
        "koliko stane ortoped",
        "koliko stane dermatolog",
        "zdravo",
        "prosti termini",
        "nujno",
        "boli me glava",
        "hvala",
        "kdo je direktor",
    ]

    scenarios: list[tuple[str, str]] = []

    # 12-turn realistic flow in one session.
    for message in multi_turn_flow:
        scenarios.append(("e2e-flow-1", message))

    # 88 one-shot situations with isolated sessions to avoid loop side-effects.
    for idx in range(88):
        msg = single_turn_pool[idx % len(single_turn_pool)]
        scenarios.append((f"e2e-single-{idx}", msg))

    assert len(scenarios) == 100

    for session_id, message in scenarios:
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
        assert "prišlo je do napake pri povezavi" not in reply.lower()
