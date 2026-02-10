import os
import time
import hmac
import hashlib
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from app.services.email_service import send_admin_notification
from app.services.reservation_service import ReservationService
from app.services.sms_service import send_booking_received_sms
from app.services.clinic_config import (
    get_clinic_config,
    list_available_clinics,
    resolve_clinic_id,
    set_current_clinic_id,
    reset_current_clinic_id,
)

router = APIRouter(prefix="/api/webhook", tags=["webhook"])

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 30  # requests per window per IP
rate_limit_log: dict[str, list[float]] = {}


class WordPressReservation(BaseModel):
    # Skupna polja
    source: str  # 'wordpress_room' | 'wordpress_table'
    name: str
    email: str
    phone: Optional[str] = None
    date: str
    people: int
    note: Optional[str] = None

    # Polja za sobe
    nights: Optional[int] = None
    room: Optional[str] = None  # 'Aljaž' | 'Ana' | 'Julija'
    country: Optional[str] = None
    adults: Optional[int] = None
    kids: Optional[str] = None
    kids_small: Optional[str] = None
    arrive: Optional[str] = None
    depart: Optional[str] = None
    confirm_via: Optional[str] = None

    # Polja za mize
    time: Optional[str] = None
    event_type: Optional[str] = None
    location: Optional[str] = None  # jedilnica
    special_needs: Optional[str] = None
    kids_count: Optional[int] = None
    kids_ages: Optional[str] = None


@router.post("/reservation")
async def receive_wordpress_reservation(
    request: Request,
    data: WordPressReservation,
    x_webhook_signature: str = Header(None),
    x_webhook_secret: str = Header(None),
    x_webhook_token: str = Header(None),
    x_admin_token: str = Header(None),
    x_clinic_id: str = Header(None),
):
    """Prejme rezervacijo iz WordPress vtičnika in jo shrani kot pending."""
    strict_clinic = os.getenv("STRICT_CLINIC_ID", "false").strip().lower() in {"1", "true", "yes", "on"}
    try:
        clinic_id = resolve_clinic_id(x_clinic_id, strict=strict_clinic)
    except ValueError:
        available = list_available_clinics()
        raise HTTPException(status_code=400, detail={"error": "unknown_clinic_id", "available": available})
    token = set_current_clinic_id(clinic_id)
    try:
        config = get_clinic_config(clinic_id=clinic_id)
        auth_cfg = config.get("auth", {}) if isinstance(config, dict) else {}
        expected = auth_cfg.get("admin_api_key")
        provided_token = x_webhook_token or x_admin_token
        if expected:
            if not provided_token or provided_token != expected:
                raise HTTPException(status_code=401, detail="Invalid webhook token")

        # rate limit per IP
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        history = rate_limit_log.get(ip, [])
        history = [ts for ts in history if now - ts < RATE_LIMIT_WINDOW]
        if len(history) >= RATE_LIMIT_MAX:
            raise HTTPException(status_code=429, detail="Too Many Requests")
        history.append(now)
        rate_limit_log[ip] = history

        # signature verification (skip if secret not set)
        secret = WEBHOOK_SECRET or ""
        if secret and not expected:
            raw_body = await request.body()
            computed = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
            expected_sig = f"sha256={computed}"
            provided = x_webhook_signature or x_webhook_secret  # backward compat
            if not provided or not hmac.compare_digest(provided, expected_sig):
                raise HTTPException(status_code=401, detail="Invalid webhook signature")

        service = ReservationService()
        res_id = service.create_reservation(
            date=data.arrive or data.date,
            people=data.people or data.adults or 0,
            reservation_type="room" if data.source == "wordpress_room" else "table",
            source=data.source,
            nights=data.nights,
            rooms=1 if data.room else None,
            name=data.name,
            phone=data.phone,
            email=data.email,
            time=data.time,
            location=data.room or data.location,
            note=data.note,
            country=data.country,
            kids=data.kids,
            kids_small=data.kids_small,
            confirm_via=data.confirm_via,
            event_type=data.event_type,
            special_needs=data.special_needs or data.kids_ages,
        )

        send_admin_notification(
            {
                "id": res_id,
                "name": data.name,
                "email": data.email,
                "phone": data.phone,
                "date": data.arrive or data.date,
                "people": data.people or data.adults,
                "reservation_type": "room" if data.source == "wordpress_room" else "table",
                "source": data.source,
            }
        )

        created = service.get_reservation(res_id)
        if created and created.get("phone"):
            send_booking_received_sms(created)

        return {"status": "ok", "reservation_id": res_id}
    finally:
        reset_current_clinic_id(token)
