from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.chat import ChatResponse
from app.services.admin_router import router as admin_router
from app.services.chat_router import router as chat_router
from app.services.reservation_service import ReservationService


def test_reservation_message_sms_channel_roundtrip() -> None:
    service = ReservationService()
    reservation_id = service.create_reservation(
        date="21.03.2026",
        people=1,
        reservation_type="table",
        source="test",
        location="Dermatološki pregled",
        name="SMS Test",
        phone="040111222",
        email="sms@test.si",
    )

    ok = service.add_reservation_message(
        reservation_id=reservation_id,
        direction="outbound",
        channel="sms",
        subject="SMS odgovor",
        body="Test SMS",
        from_phone="+38640111222",
        to_phone="+38640111223",
        provider_message_sid="SM123",
    )
    assert ok

    messages = service.list_reservation_messages(reservation_id)
    assert messages
    last = messages[-1]
    assert last.get("channel") == "sms"
    assert last.get("from_phone") == "+38640111222"
    assert last.get("to_phone") == "+38640111223"
    assert last.get("provider_message_sid") == "SM123"


def test_admin_send_sms_endpoint(monkeypatch) -> None:
    service = ReservationService()
    reservation_id = service.create_reservation(
        date="22.03.2026",
        people=1,
        reservation_type="table",
        source="test",
        location="Okulistični pregled",
        name="Admin SMS",
        phone="040555666",
        email="adminsms@test.si",
    )

    from app.services import admin_router as admin_mod

    monkeypatch.setattr(
        admin_mod,
        "send_sms",
        lambda to, body: {
            "success": True,
            "mock": True,
            "message_sid": "SM-MOCK-1",
            "to": to,
            "message_length": len(body),
        },
    )

    app = FastAPI()
    app.include_router(admin_router)
    client = TestClient(app)

    resp = client.post(
        "/api/admin/send-sms",
        json={
            "reservation_id": reservation_id,
            "phone": "040555666",
            "body": "Pozdrav iz admina",
            "set_processing": False,
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("ok") is True

    messages = service.list_reservation_messages(reservation_id)
    assert any(m.get("channel") == "sms" and "Pozdrav iz admina" in (m.get("body") or "") for m in messages)


def test_sms_webhook_logs_and_replies(monkeypatch) -> None:
    service = ReservationService()
    reservation_id = service.create_reservation(
        date="23.03.2026",
        people=1,
        reservation_type="table",
        source="test",
        location="Ortopedski pregled",
        name="Webhook SMS",
        phone="040777888",
        email="webhooksms@test.si",
    )

    from app.services import chat_router as chat_mod
    from app.services import sms_service as sms_mod

    sent_messages: list[tuple[str, str]] = []

    def _fake_send_sms(to: str, message: str, mock_override=None):
        sent_messages.append((to, message))
        return {
            "success": True,
            "mock": True,
            "message_sid": f"SM-MOCK-{len(sent_messages)}",
            "to": to,
            "message_length": len(message),
        }

    async def _fake_chat(_request):
        return ChatResponse(reply="Delovni čas: Pon-Pet 08:00-18:00", session_id="sms:mock")

    monkeypatch.setattr(sms_mod, "send_sms", _fake_send_sms)
    monkeypatch.setattr(chat_mod, "chat", _fake_chat)

    app = FastAPI()
    app.include_router(chat_router)
    client = TestClient(app)

    resp = client.post(
        "/chat/sms-webhook",
        data={
            "From": "+38640777888",
            "To": "+12025550123",
            "Body": "kak je delovni čas",
            "MessageSid": "SM-IN-1",
        },
    )

    assert resp.status_code == 200
    assert "<Response>" in resp.text
    assert sent_messages, "SMS odgovor ni bil poslan"

    messages = service.list_reservation_messages(reservation_id)
    sms_msgs = [m for m in messages if m.get("channel") == "sms"]
    assert len(sms_msgs) >= 2
    assert any((m.get("direction") == "inbound" and "delovni čas" in (m.get("body") or "").lower()) for m in sms_msgs)
    assert any((m.get("direction") == "outbound" and "pon-pet" in (m.get("body") or "").lower()) for m in sms_msgs)
