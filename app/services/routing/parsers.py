from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from app.services.health_center_extensions import get_service_map, get_services
from app.services.routing.confidence import detect_service_type as detect_service_type_conf
from app.services.routing.intent_engine import classify_intent_llm
from app.services.routing.intent_labels import (
    INTENT_BOOK_GENERAL,
    INTENT_CHECK_AVAILABILITY,
    INTENT_GREETING,
    INTENT_HEALTH_SYMPTOMS,
    INTENT_INFO_CONTACT,
    INTENT_INFO_HOURS,
    INTENT_INFO_NAROCANJE,
    INTENT_INFO_PRICES,
    INTENT_INFO_SERVICES,
    INTENT_INFO_TEAM,
    INTENT_QUESTION,
    INTENT_THANKS,
)
from app.services.routing.locale_sl import (
    AVAILABILITY_PHRASES,
    AVAILABILITY_WORDS,
    BOOKING_INFO_PHRASES,
    BOOKING_KEYWORDS,
    BOOKING_KEYWORDS_EXTENDED,
    CONTACT_WORDS,
    FULL_NAME_BLOCKED_SINGLE,
    FULL_NAME_BLOCKED_TOKENS,
    GREETING_WORDS,
    HOURS_WORDS,
    PRICE_WORDS,
    RELATIVE_DATES,
    SERVICE_INFO_TOKENS,
    SERVICE_LIST_WORDS,
    SKIP_SERVICE_KEYWORDS,
    SYMPTOM_PATTERNS,
    SYMPTOM_WORDS,
    TEAM_WORDS,
    THANKS_WORDS,
)


def _service_mentioned_in_message(message: str, service: str) -> bool:
    lowered = message.lower()
    keywords = get_service_map().get(service, [])
    for kw in keywords:
        if re.search(r"\b" + re.escape(kw), lowered):
            return True
    return False


def _has_booking_keywords(message: str) -> bool:
    lowered = message.lower()
    return any(word in lowered for word in BOOKING_KEYWORDS)


def classify_intent_rules(message: str, history: list | None = None, clinic_id: str | None = None) -> str:
    lowered = message.lower()
    services = get_services(clinic_id=clinic_id)
    service_map = get_service_map(clinic_id=clinic_id)

    if any(pattern in lowered for pattern in SYMPTOM_PATTERNS):
        return INTENT_HEALTH_SYMPTOMS

    has_symptom = any(word in lowered for word in SYMPTOM_WORDS)
    has_booking = any(word in lowered for word in BOOKING_KEYWORDS_EXTENDED)
    if has_symptom and not has_booking:
        return INTENT_HEALTH_SYMPTOMS

    if any(phrase in lowered for phrase in BOOKING_INFO_PHRASES):
        return INTENT_INFO_NAROCANJE

    if any(phrase in lowered for phrase in AVAILABILITY_PHRASES):
        return INTENT_CHECK_AVAILABILITY

    has_price = any(word in lowered for word in PRICE_WORDS)
    has_booking_kw = any(word in lowered for word in BOOKING_KEYWORDS_EXTENDED)
    if has_price and has_booking_kw:
        return INTENT_INFO_PRICES

    if any(word in lowered for word in BOOKING_KEYWORDS_EXTENDED):
        for service_key, variations in service_map.items():
            if any(var in lowered for var in variations):
                return f"book_{service_key}"
        return INTENT_BOOK_GENERAL

    if any(word in lowered for word in HOURS_WORDS):
        return INTENT_INFO_HOURS

    if any(word in lowered for word in AVAILABILITY_WORDS):
        return INTENT_CHECK_AVAILABILITY

    for service_key in services.keys():
        if service_key in lowered or any(var in lowered for var in service_map.get(service_key, [])):
            if "?" not in lowered and not any(tok in lowered for tok in SERVICE_INFO_TOKENS):
                return f"book_{service_key}"
            return f"info_{service_key}"

    if any(word in lowered for word in SERVICE_LIST_WORDS):
        return INTENT_INFO_SERVICES

    if any(word in lowered for word in PRICE_WORDS):
        return INTENT_INFO_PRICES

    if any(word in lowered for word in TEAM_WORDS):
        return INTENT_INFO_TEAM

    if any(word in lowered for word in CONTACT_WORDS):
        return INTENT_INFO_CONTACT

    if any(word in lowered for word in THANKS_WORDS):
        return INTENT_THANKS

    if any(word in lowered for word in GREETING_WORDS):
        return INTENT_GREETING

    return INTENT_QUESTION


def classify_intent(message: str, history: list | None = None, clinic_id: str | None = None) -> str:
    has_price_kw = any(word in message.lower() for word in PRICE_WORDS)
    if (
        _has_booking_keywords(message)
        and not has_price_kw
        and extract_service_type(message, clinic_id=clinic_id) is None
        and not any(phrase in message.lower() for phrase in BOOKING_INFO_PHRASES)
    ):
        return INTENT_BOOK_GENERAL

    rules_intent = classify_intent_rules(message, history, clinic_id=clinic_id)

    if rules_intent in {
        INTENT_GREETING,
        INTENT_THANKS,
        INTENT_INFO_HOURS,
        INTENT_INFO_CONTACT,
        INTENT_INFO_PRICES,
        INTENT_INFO_SERVICES,
        INTENT_CHECK_AVAILABILITY,
        INTENT_INFO_NAROCANJE,
        INTENT_HEALTH_SYMPTOMS,
    }:
        return rules_intent

    if rules_intent.startswith("book_") or rules_intent.startswith("info_"):
        return rules_intent

    result = classify_intent_llm(message, history)
    intent = result.get("intent", "other")
    service = result.get("service")

    if intent == "booking":
        if service and _service_mentioned_in_message(message, service):
            return f"book_{service}"
        return INTENT_BOOK_GENERAL
    if intent == "health_advice":
        return INTENT_QUESTION
    if intent == "question":
        return INTENT_QUESTION
    if intent in {
        INTENT_INFO_NAROCANJE,
        INTENT_INFO_SERVICES,
        INTENT_INFO_PRICES,
        INTENT_INFO_CONTACT,
        INTENT_INFO_HOURS,
        INTENT_GREETING,
    }:
        return intent
    return INTENT_QUESTION


def extract_date_from_message(message: str) -> Optional[str]:
    match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", message)
    if match:
        day, month, year = match.groups()
        return f"{day.zfill(2)}.{month.zfill(2)}.{year}"

    match = re.search(r"(?<!\d)(\d{1,2})\.(\d{1,2})(?!\d)", message)
    if match:
        day_raw, month_raw = match.groups()
        day = int(day_raw)
        month = int(month_raw)
        today = datetime.now()
        try:
            candidate = datetime(today.year, month, day)
        except ValueError:
            return None
        if candidate.date() < today.date():
            try:
                candidate = datetime(today.year + 1, month, day)
            except ValueError:
                return None
        return candidate.strftime("%d.%m.%Y")

    lowered = message.lower()
    today = datetime.now()
    for token, offset in RELATIVE_DATES.items():
        if token in lowered:
            return (today + timedelta(days=offset)).strftime("%d.%m.%Y")
    return None


def extract_time_from_message(message: str) -> Optional[str]:
    match = re.search(r"(\d{1,2}):(\d{2})", message)
    if match:
        hour, minute = match.groups()
        return f"{hour.zfill(2)}:{minute}"

    match = re.search(r"(\d{1,2})\.(\d{2})", message)
    if match:
        hour, minute = match.groups()
        return f"{hour.zfill(2)}:{minute}"

    match = re.search(r"(\d{1,2})-(\d{2})", message)
    if match:
        hour, minute = match.groups()
        return f"{hour.zfill(2)}:{minute}"

    match = re.search(r"\b(\d{3,4})\b", message)
    if match:
        time_str = match.group(1)
        if len(time_str) == 4:
            hour, minute = time_str[:2], time_str[2:]
            return f"{hour}:{minute}"
        if len(time_str) == 3:
            hour, minute = time_str[0], time_str[1:]
            return f"{hour.zfill(2)}:{minute}"

    match = re.search(r"ob\s+(\d{1,2})", message.lower())
    if match:
        hour = match.group(1)
        return f"{hour.zfill(2)}:00"
    return None


def is_likely_full_name(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 3 or "?" in stripped:
        return False
    lowered = stripped.lower()
    if any(token in lowered for token in FULL_NAME_BLOCKED_TOKENS):
        return False
    if any(char.isdigit() for char in stripped):
        return False
    parts = [p for p in stripped.split() if p]
    if len(parts) >= 2:
        return True
    single = parts[0].lower() if parts else ""
    if single in FULL_NAME_BLOCKED_SINGLE:
        return False
    return len(single) >= 3


def extract_service_type(message: str, clinic_id: str | None = None) -> Optional[str]:
    lowered = message.lower()
    service_map = get_service_map(clinic_id=clinic_id)
    detected = detect_service_type_conf(lowered, service_map=service_map)
    if detected:
        return detected.lower()

    for service_key, variations in service_map.items():
        for var in variations:
            if var in SKIP_SERVICE_KEYWORDS:
                continue
            if re.search(r"\b" + re.escape(var) + r"\b", lowered):
                return service_key
    return None


def detect_service_from_message(message: str, clinic_id: str | None = None) -> Optional[str]:
    return extract_service_type(message, clinic_id=clinic_id)

