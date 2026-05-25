"""
MDT&T chat router — Kovačnik V2 architecture.
LLM-first for all info; booking via widget form.
"""
from __future__ import annotations

import threading
import uuid
from typing import Optional

from fastapi import APIRouter, Form, Request, UploadFile, File
from fastapi.responses import Response

from app.models.chat import ChatRequest, ChatResponse
from app.services.mdt_llm import chat as llm_chat
from app.services.reservation_service import ReservationService
from app.services.email_service import send_guest_confirmation, send_admin_notification
from app.services.sms_service import send_booking_received_sms

router = APIRouter(prefix="/chat", tags=["chat"])

# In-memory session history: session_id → list of {"role", "content"}
_sessions: dict[str, list[dict[str, str]]] = {}

_MAX_HISTORY = 10


def _get_history(session_id: str) -> list[dict[str, str]]:
    return _sessions.get(session_id, [])


def _append_history(session_id: str, role: str, content: str) -> None:
    if session_id not in _sessions:
        _sessions[session_id] = []
    _sessions[session_id].append({"role": role, "content": content})
    if len(_sessions[session_id]) > _MAX_HISTORY:
        _sessions[session_id] = _sessions[session_id][-_MAX_HISTORY:]


def _send_notifications_async(payload: dict) -> None:
    def _worker() -> None:
        try:
            send_guest_confirmation(payload)
            send_admin_notification(payload)
            if payload.get("phone"):
                send_booking_received_sms(payload)
        except Exception as exc:
            print(f"[NOTIFY] Async send failed: {exc}")
    threading.Thread(target=_worker, daemon=True).start()


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Main chat endpoint: booking form submission or LLM call."""
    raw_session_id = request.session_id or str(uuid.uuid4())
    session_id = raw_session_id.strip()

    # Booking form submission (from widget)
    if request.booking_form and (request.booking_form.name or request.booking_form.phone):
        bf = request.booking_form
        try:
            rs = ReservationService()
            rs.create_reservation(
                date=bf.date or "",
                people=1,
                reservation_type="appointment",
                source="widget_form",
                name=bf.name,
                phone=bf.phone,
                email=bf.email,
                note=bf.note,
                service_type=bf.service,
            )
        except Exception as e:
            print(f"[BOOKING] Reservation save failed: {e}")
        return ChatResponse(
            reply="Hvala za prijavo! Kontaktirali vas bomo za potrditev termina.",
            session_id=raw_session_id,
        )

    message = (request.message or "").strip()
    if not message:
        return ChatResponse(
            reply="Prosim napišite sporočilo, da vam lahko pomagam.",
            session_id=raw_session_id,
        )

    history = _get_history(session_id)

    result = llm_chat(message=message, history=history)
    reply = result.get("reply", "Oprostite, prišlo je do napake. Pokličite nas: 02 23 53 552.")

    _append_history(session_id, "user", message)
    _append_history(session_id, "assistant", reply)

    return ChatResponse(
        reply=reply,
        session_id=raw_session_id,
        metadata={"router": "llm_direct"},
    )


@router.post("/voice")
async def voice_input(
    file: UploadFile = File(...),
    session_id: str = None,
    clinic_id: str = None,
):
    """Accepts audio, transcribes with Whisper, returns LLM reply."""
    from app.services.voice_service import get_voice_service

    voice_service = get_voice_service()

    if not voice_service.is_available():
        return {
            "success": False,
            "error": "Glasovni servis ni na voljo. Prosimo pišite sporočilo.",
            "transcription": None,
            "reply": None,
        }

    try:
        content = await file.read()

        validation = voice_service.validate_audio_file(file.filename or "audio.wav", len(content))
        if not validation["valid"]:
            return {
                "success": False,
                "error": validation["error"],
                "transcription": None,
                "reply": None,
            }

        result = await voice_service.transcribe_from_bytes(content, file.filename or "audio.wav")

        if not result["success"]:
            return {
                "success": False,
                "error": result.get("error", "Napaka pri transkripciji"),
                "transcription": None,
                "reply": None,
            }

        transcribed_text = result["text"]
        chat_request = ChatRequest(
            message=transcribed_text,
            session_id=session_id,
            clinic_id=clinic_id,
        )
        chat_response = await chat(chat_request)

        return {
            "success": True,
            "transcription": transcribed_text,
            "reply": chat_response.reply,
            "session_id": chat_response.session_id,
            "duration_seconds": result.get("duration_seconds"),
        }

    except Exception as e:
        print(f"[VOICE] Error: {e}")
        return {
            "success": False,
            "error": f"Napaka pri obdelavi: {e}",
            "transcription": None,
            "reply": None,
        }


@router.post("/sms-webhook")
async def sms_webhook(
    request: Request,
    From: str = Form(default=""),
    Body: str = Form(default=""),
    To: str = Form(default=""),
    MessageSid: str = Form(default=""),
):
    """Twilio webhook — processes patient SMS replies to reminders."""
    try:
        from app.services.reminder_scheduler import handle_sms_response
        from app.services.sms_service import send_sms

        form = await request.form()
        from_value = (From or form.get("From") or form.get("from") or form.get("sender") or form.get("phone") or "").strip()
        body_value = (Body or form.get("Body") or form.get("body") or form.get("message") or form.get("text") or form.get("m") or "").strip()
        to_value = (To or form.get("To") or form.get("to") or "").strip()
        sid_value = (MessageSid or form.get("MessageSid") or form.get("message_id") or form.get("smsId") or form.get("id") or "").strip()

        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'

        if not from_value or not body_value:
            print(f"[SMS WEBHOOK] Missing sender/body. form_keys={list(form.keys())}")
            return Response(content=twiml, media_type="application/xml")

        print(f"[SMS WEBHOOK] Received from {from_value}: {body_value} (SID: {sid_value})")

        reservation_service = ReservationService()
        reservation = reservation_service.find_latest_reservation_by_phone(from_value)
        reservation_id = reservation.get("id") if reservation else None

        if reservation_id:
            reservation_service.add_reservation_message(
                reservation_id=reservation_id,
                direction="inbound",
                channel="sms",
                subject="Prejet SMS",
                body=body_value,
                from_phone=from_value,
                to_phone=to_value,
                message_id=sid_value or None,
                provider_message_sid=sid_value or None,
            )

        quick_actions = {"da", "yes", "ok", "pridem", "potrjujem", "prestav", "prestavi", "odpovej", "odpoved", "cancel", "ne"}
        if any(token in body_value.lower() for token in quick_actions):
            result = handle_sms_response(from_value, body_value)
            reply_text = result.get("response_message") or ""
        else:
            sms_session_id = f"sms:{''.join(ch for ch in str(from_value) if ch.isdigit())}"
            chat_req = ChatRequest(message=body_value, session_id=sms_session_id, clinic_id=None)
            chat_resp = await chat(chat_req)
            reply_text = (chat_resp.reply or "").strip()

        if not reply_text:
            reply_text = "Hvala za sporočilo. Za pomoč pokličite 02 23 53 552."

        send_result = send_sms(from_value, reply_text)

        if reservation_id and reply_text:
            reservation_service.add_reservation_message(
                reservation_id=reservation_id,
                direction="outbound",
                channel="sms",
                subject="SMS odgovor",
                body=reply_text,
                from_phone=to_value,
                to_phone=from_value,
                message_id=None,
                provider_message_sid=send_result.get("message_sid"),
            )

        return Response(content=twiml, media_type="application/xml")

    except Exception as e:
        print(f"[SMS WEBHOOK] Error: {e}")
        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
        return Response(content=twiml, media_type="application/xml")
