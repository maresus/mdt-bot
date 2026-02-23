"""
Router V2 - klasifikacija sporočil v standardiziran JSON.
Zdravstveni Center verzija z unified routing sistemom.

Feature flag: USE_UNIFIED_ROUTER=true za nov sistem
"""
from __future__ import annotations

import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
from typing import Any, Dict, Optional

# Import unified routing system
from .routing import route, IntentType, SwitchAction, detect_service_type
from .session import get_unified_state, blank_unified_state

# Feature flag
USE_UNIFIED_ROUTER = os.environ.get("USE_UNIFIED_ROUTER", "").lower() in ("true", "1", "yes")


def _extract_date(text: str) -> Optional[str]:
    match = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})\b", text)
    if not match:
        return None
    day, month, year = match.groups()
    year = year if len(year) == 4 else f"20{year.zfill(2)}"
    return f"{day.zfill(2)}.{month.zfill(2)}.{year}"


def _extract_time(text: str) -> Optional[str]:
    match = re.search(r"\b(\d{1,2})[:.](\d{2})\b", text)
    if not match:
        return None
    hour, minute = match.groups()
    return f"{hour.zfill(2)}:{minute}"


def _extract_phone(text: str) -> Optional[str]:
    """Extract phone number from text."""
    digits = re.sub(r"\D+", "", text)
    if len(digits) >= 7:
        return digits
    return None


# --- Logging setup ---
_router_logger = logging.getLogger("router_v2")
if not _router_logger.handlers:
    _router_logger.setLevel(logging.INFO)
    try:
        handler = RotatingFileHandler("data/router_debug.log", maxBytes=1_000_000, backupCount=3)
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        _router_logger.addHandler(handler)
    except Exception:
        pass  # Ignore if data folder doesn't exist

_metrics = {"info_hits": 0, "booking_starts": 0, "unified_calls": 0}


def _unified_route_message(
    message: str,
    has_active_booking: bool = False,
    booking_step: Optional[str] = None,
    session_id: str = "default",
) -> Dict[str, Any]:
    """
    Route message using unified routing system.
    Returns same format as legacy route_message for compatibility.
    """
    _metrics["unified_calls"] += 1
    text = message.lower()

    # Get state snapshot for routing only (do not mutate persisted state here).
    persisted_state = get_unified_state(session_id)
    state = dict(persisted_state)

    # Set flow status for this routing pass
    if has_active_booking:
        state["flow"] = "appointment"
        state["step"] = booking_step or "date"
    else:
        state["flow"] = "idle"
        state["step"] = None

    # Run unified router
    decision = route(message, state)

    # Map IntentType to legacy intent strings
    intent_map = {
        IntentType.BOOKING_APPOINTMENT: "BOOKING_APPOINTMENT",
        IntentType.SERVICE_INFO: "INFO",
        IntentType.PRICE: "INFO",
        IntentType.INFO: "INFO",
        IntentType.URGENCY: "URGENCY",
        IntentType.GREETING: "GREETING",
        IntentType.GOODBYE: "GOODBYE",
        IntentType.AFFIRMATIVE: "AFFIRMATIVE",
        IntentType.NEGATIVE: "NEGATIVE",
        IntentType.GENERAL: "GENERAL",
    }
    intent = intent_map.get(decision.primary_intent, "GENERAL")

    # Handle booking continue (affirmative during booking)
    if has_active_booking and decision.primary_intent == IntentType.AFFIRMATIVE:
        intent = "BOOKING_CONTINUE"

    # Detect service type
    service_type = decision.service_type or detect_service_type(text)

    # Determine if this is an interrupt
    is_interrupt = decision.action == SwitchAction.SOFT_INTERRUPT

    # Build info_key for compatibility
    info_key = None
    if decision.primary_intent == IntentType.INFO:
        if "parking" in text:
            info_key = "parking"
        elif "delovni" in text or "odprt" in text or "kdaj" in text:
            info_key = "odpiralni_cas"
        elif "telefon" in text or "številka" in text:
            info_key = "kontakt"
        elif "email" in text or "e-mail" in text:
            info_key = "kontakt"
        elif "kje" in text or "lokacija" in text or "naslov" in text:
            info_key = "lokacija"
        else:
            info_key = "splošno"
    elif decision.primary_intent == IntentType.SERVICE_INFO:
        info_key = f"storitev:{service_type}" if service_type else "storitve"
    elif decision.primary_intent == IntentType.PRICE:
        info_key = "cenik"

    # Extract entities
    entities: Dict[str, Any] = {}
    date = _extract_date(text)
    if date:
        entities["date"] = date
    time_val = _extract_time(text)
    if time_val:
        entities["time"] = time_val
    phone = _extract_phone(text)
    if phone:
        entities["phone"] = phone
    if service_type:
        entities["service_type"] = service_type

    # Handle phone input during booking
    if booking_step == "awaiting_phone" and phone:
        intent = "BOOKING_CONTINUE"

    # Update metrics
    if intent == "INFO":
        _metrics["info_hits"] += 1
    if intent == "BOOKING_APPOINTMENT":
        _metrics["booking_starts"] += 1

    record = {
        "routing": {
            "intent": intent,
            "confidence": decision.confidence,
            "is_interrupt": is_interrupt,
            "action": decision.action.value,
        },
        "context": {
            "info_key": info_key,
            "service_type": service_type,
            "needs_soft_sell": False,
        },
        "entities": entities,
        "meta": {
            "has_active_booking": has_active_booking,
            "booking_step": booking_step,
            "unified_router": True,
        },
    }

    # Log
    try:
        _router_logger.info(
            json.dumps(
                {
                    "intent": intent,
                    "confidence": decision.confidence,
                    "info_key": info_key,
                    "service_type": service_type,
                    "is_interrupt": is_interrupt,
                    "booking_step": booking_step,
                    "message": message[:200],
                    "metrics": _metrics.copy(),
                    "unified": True,
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        pass

    return record


def route_message(
    message: str,
    has_active_booking: bool = False,
    booking_step: Optional[str] = None,
    session_id: str = "default",
) -> Dict[str, Any]:
    """
    Main routing function.
    Uses unified router when USE_UNIFIED_ROUTER=true.
    """
    if USE_UNIFIED_ROUTER:
        return _unified_route_message(message, has_active_booking, booking_step, session_id)

    # Legacy routing (kept for backwards compatibility)
    return _legacy_route_message(message, has_active_booking, booking_step)


def _legacy_route_message(
    message: str,
    has_active_booking: bool = False,
    booking_step: Optional[str] = None,
) -> Dict[str, Any]:
    """Legacy routing - kept for backwards compatibility."""
    text = message.lower()

    # Simple health center intent detection (legacy)
    intent = "GENERAL"
    info_key = None
    service_type = None

    # Greeting/goodbye
    if any(w in text for w in ["zdravo", "zdravjo", "zdwavo", "živjo", "dober dan", "hello", "pozdravljeni"]):
        intent = "GREETING"
    elif any(w in text for w in ["hvala", "adijo", "nasvidenje"]):
        intent = "GOODBYE"
    # Booking
    elif any(w in text for w in ["termin", "naročiti", "naročim", "naročilo", "pregled"]):
        intent = "BOOKING_APPOINTMENT"
        service_type = detect_service_type(text)
    # Info
    elif any(w in text for w in ["kdaj", "kje", "odprt", "parking", "telefon"]):
        intent = "INFO"
        info_key = "splošno"
    # Price
    elif any(w in text for w in ["cena", "koliko stane", "cenik"]):
        intent = "INFO"
        info_key = "cenik"

    # Handle booking continue
    if has_active_booking:
        if text in {"da", "ja", "ok", "okej"}:
            intent = "BOOKING_CONTINUE"
        elif intent not in {"BOOKING_APPOINTMENT", "GREETING", "GOODBYE"}:
            if booking_step == "awaiting_phone":
                phone = _extract_phone(text)
                if phone:
                    intent = "BOOKING_CONTINUE"

    entities: Dict[str, Any] = {}
    date = _extract_date(text)
    if date:
        entities["date"] = date
    time_val = _extract_time(text)
    if time_val:
        entities["time"] = time_val
    if service_type:
        entities["service_type"] = service_type

    return {
        "routing": {
            "intent": intent,
            "confidence": 0.8,
            "is_interrupt": False,
        },
        "context": {
            "info_key": info_key,
            "service_type": service_type,
            "needs_soft_sell": False,
        },
        "entities": entities,
        "meta": {
            "has_active_booking": has_active_booking,
            "booking_step": booking_step,
            "unified_router": False,
        },
    }
