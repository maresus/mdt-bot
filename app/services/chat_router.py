import re
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Optional
import uuid
import threading

from fastapi import APIRouter, HTTPException

from app.models.chat import ChatRequest, ChatResponse
from app.services.reservation_service import ReservationService
from app.services.email_service import send_guest_confirmation, send_admin_notification
from app.services.sms_service import send_booking_received_sms
from app.services.health_center_extensions import (
    validate_appointment_rules,
    format_appointment_summary,
    get_available_time_slots,
    get_service_info,
    format_all_services_summary,
    get_service_map,
    get_services,
)
from app.rag.rag_engine import rag_engine
from app.rag.chroma_service import answer_tourist_question, is_tourist_query
from app.services.chat_history_service import get_chat_history_service
from app.services.clinic_config import (
    get_clinic_config,
    get_info_response as clinic_get_info_response,
    get_domain_response,
    get_fast_pass_match,
    list_available_clinics,
    resolve_clinic_id,
    set_current_clinic_id,
    reset_current_clinic_id,
)

# Unified Routing System imports
from app.services.session.unified_state import (
    get_unified_state,
    reset_unified_state,
    is_in_flow,
    get_current_step,
    start_flow,
    get_appointment_data,
    is_appointment_complete,
    StateManager,
    FlowType,
    FlowStep,
)
from app.services.routing.unified_router import route as unified_route, IntentType
from app.services.routing.confidence import detect_service_type as detect_service_type_conf
from app.services.routing.nlp_utils import is_affirmative, is_negative
from app.services.routing.state_manager import ConversationTracker, SimpleCache
from app.services.routing.intent_engine import classify_intent_llm
from app.services.routing.interrupt_handler import build_interrupt_response, build_resume_prompt
from app.services.routing.advice import advice_only, advice_only_headache
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
from app.services.routing.response_keys import (
    INFO_KEY_CONTACT,
    INFO_KEY_HOURS,
    INFO_KEY_LOCATION,
    INFO_KEY_PARKING,
    INFO_KEY_PRICES,
    INFO_KEY_SERVICES,
    INFO_KEYS_DIRECT,
    INFO_CONTACT_SHORT,
    INFO_SERVICE_DERMATOLOG,
    INFO_SERVICE_ESTETSKI_POSEG,
    INFO_SERVICE_FIZIOTERAPIJA,
    INFO_SERVICE_KOZMETIKA,
    INFO_SERVICE_LASERSKI_POSEG,
    INFO_SERVICE_OKULIST,
    INFO_SERVICE_ORTOPED,
)
from app.services.routing.locale_sl import (
    AVAILABILITY_PHRASES,
    AVAILABILITY_WORDS,
    BOOKING_INFO_PHRASES,
    BOOKING_KEYWORDS,
    BOOKING_KEYWORDS_EXTENDED,
    BOOKING_RELEVANT_KEYS,
    CONTACT_WORDS,
    CONTACT_ROUTE_WORDS,
    CRITICAL_INFO_KEYS,
    FULL_NAME_BLOCKED_SINGLE,
    FULL_NAME_BLOCKED_TOKENS,
    GREETING_WORDS,
    HOURS_WORDS,
    PRICE_WORDS,
    QUESTION_MARKERS,
    RELATIVE_DATES,
    SERVICE_INFO_TOKENS,
    SERVICE_KEYWORDS,
    SERVICE_LIST_WORDS,
    SYMPTOM_MARKERS,
    SYMPTOM_PATTERNS,
    SYMPTOM_WORDS,
    SKIP_SERVICE_KEYWORDS,
    TEAM_WORDS,
    THANKS_WORDS,
)
from app.services.knowledge.hybrid_kb import answer_with_hybrid_kb
from app.core.response_formatter import format_response
from app.services.flows.booking_flow import (
    BookingFlowDeps,
    get_resume_prompt as booking_get_resume_prompt,
    handle_appointment_booking as booking_handle_appointment_booking,
)
from app.services.flows.info_flow import pick_info_key
from app.services.flows.interrupt_flow import InterruptFlowDeps, resolve_interrupt_answer
from app.services.flows.booking_interrupt_policy import (
    BookingInterruptDeps,
    handle_booking_interrupt,
)

router = APIRouter(prefix="/chat", tags=["chat"])
USE_ROUTER_V2 = True
USE_FULL_KB_LLM = False  # False = RAG (fast), True = full KB (slow)
# D4: legacy kill - unified router is always enabled.
USE_UNIFIED_ROUTER = True
SHORT_MODE = os.getenv("SHORT_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}

# ========== ANTI-LOOP & CACHE MECHANISMS ==========

# Initialize trackers
conversation_tracker = ConversationTracker()
response_cache = SimpleCache()

# Chat history service (for persistent storage)
def save_chat_message(
    session_id: str,
    role: str,
    content: str,
    intent: Optional[str] = None,
    service_mentioned: Optional[str] = None,
    booking_step: Optional[str] = None,
    response_cached: bool = False,
    metadata: Optional[dict] = None
):
    """
    Save chat message to persistent storage (non-blocking)

    Args:
        session_id: Session ID
        role: "user" or "assistant"
        content: Message content
        intent: Classified intent
        service_mentioned: Service mentioned
        booking_step: Current booking step
        response_cached: Whether response was cached
        metadata: Additional metadata (e.g., confidence scores)
    """
    try:
        history_service = get_chat_history_service()
        history_service.save_message(
            session_id=session_id,
            role=role,
            content=content,
            intent=intent,
            service_mentioned=service_mentioned,
            booking_step=booking_step,
            response_cached=response_cached,
            metadata=metadata
        )
    except Exception as e:
        # Non-blocking - don't fail request if storage fails
        print(f"[CHAT_HISTORY] Failed to save message: {e}")

# ========== ZDRAVSTVENI CENTER INFO ODGOVORI (YAML) ==========
def _default_help_prompt(clinic_id: str | None = None) -> str:
    return get_domain_response(
        "general",
        "help_prompt",
        default="How can I help?",
        clinic_id=clinic_id,
    )


def _get_info_response(key: str, clinic_id: str | None = None) -> str:
    # Prefer domain-configured info facts (config/clinics/<id>/info.yaml), then legacy clinic config.
    domain_value = get_domain_response("info", key, default=None, clinic_id=clinic_id)
    if isinstance(domain_value, str) and domain_value.strip():
        return domain_value
    return clinic_get_info_response(key, _default_help_prompt(clinic_id=clinic_id), clinic_id=clinic_id)

def get_response(key: str, clinic_id: str | None = None, **kwargs: Any) -> str:
    """Temporary response lookup wrapper for cleanup work."""
    if "." in key:
        domain, rest = key.split(".", 1)
        response = get_domain_response(domain, rest, default=None, clinic_id=clinic_id)
        if isinstance(response, str):
            return response.format_map({**kwargs})
    if key.startswith("info."):
        info_key = key.split(".", 1)[1]
        return get_domain_response("info", info_key, default=_get_info_response(info_key, clinic_id=clinic_id), clinic_id=clinic_id)
    return _get_info_response(INFO_KEY_LOCATION, clinic_id=clinic_id)


def _get_uncertain_marker(clinic_id: str | None = None) -> str:
    return get_domain_response("general", "uncertain_marker", default="I'm not sure", clinic_id=clinic_id)


def _rag_info_answer(question: str, fallback_key: str, clinic_id: str | None = None) -> str:
    """Return KB/RAG-backed answer for info queries, fallback to hardcoded info."""
    try:
        results = rag_engine.search(question, top_k=3)
    except Exception as e:
        print(f"[RAG] Search failed: {e}")
        results = []

    if not results:
        return _get_info_response(fallback_key, clinic_id=clinic_id)

    best = results[0]
    content = (best.content or "").strip()
    if not content:
        return _get_info_response(fallback_key, clinic_id=clinic_id)

    max_len = 700
    if len(content) > max_len:
        snippet = content[:max_len]
        last_dot = snippet.rfind(".")
        if last_dot > 200:
            snippet = snippet[: last_dot + 1]
    else:
        snippet = content

    if best.url:
        label = get_domain_response(
            "general",
            "more_info_label",
            default="More info:",
            clinic_id=clinic_id,
        )
        return f"{snippet}\n\n{label} {best.url}"
    return snippet

def _send_reservation_emails_async(payload: dict) -> None:
    """Send appointment notifications asynchronously (email + SMS)."""
    def _worker() -> None:
        try:
            send_guest_confirmation(payload)
            send_admin_notification(payload)
            if payload.get("phone"):
                send_booking_received_sms(payload)
        except Exception as exc:
            print(f"[NOTIFY] Async send failed: {exc}")
    threading.Thread(target=_worker, daemon=True).start()

# Load full knowledge base
FULL_KB_TEXT = ""
try:
    kb_path = Path(__file__).resolve().parents[2] / "knowledge.jsonl"
    if kb_path.exists():
        chunks = []
        for line in kb_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                text = obj.get("text", "")
                if text:
                    chunks.append(text)
            except Exception:
                pass
        FULL_KB_TEXT = "\n\n".join(chunks)
except Exception as e:
    print(f"[KB] Failed to load knowledge base: {e}")

def _blank_appointment_state() -> dict[str, Optional[str | int]]:
    """Blank state for appointment booking"""
    return {
        "step": None,
        "service_type": None,  # dermatolog, ortoped, okulist, ...
        "date": None,
        "time": None,
        "name": None,
        "phone": None,
        "email": None,
        "reason": None,  # Razlog obiska
        "patient_age": None,
        "patient_health_card": None,
        "note": None,
        "waiting_resume_confirmation": False,  # Flag for OFF-TOPIC pause
        "awaiting_booking_confirmation": False,
    }

# Session states
appointment_states: dict[str, dict[str, Optional[str | int]]] = {}
conversation_state: dict[str, dict[str, Any]] = {}  # Session → metadata (confidence, etc.)
conversation_history: list[dict[str, str]] = []
last_interaction: Optional[datetime] = None
chat_session_id: str = str(uuid.uuid4())[:8]
last_user_message_by_session: dict[str, str] = {}

def get_appointment_state(session_id: str) -> dict[str, Optional[str | int]]:
    """Get or create appointment state for session"""
    if session_id not in appointment_states:
        appointment_states[session_id] = _blank_appointment_state()
    return appointment_states[session_id]

def reset_appointment_state(state: dict[str, Optional[str | int]]) -> None:
    """Reset appointment state"""
    state.update(_blank_appointment_state())


def _service_mentioned_in_message(message: str, service: str) -> bool:
    """Check if service is explicitly mentioned in the message (word boundary check)"""
    import re
    lowered = message.lower()
    keywords = SERVICE_KEYWORDS.get(service, [])
    # Use word boundary matching to avoid substring issues
    for kw in keywords:
        if re.search(r'\b' + re.escape(kw), lowered):
            return True
    return False


def classify_intent(message: str, history: list = None, clinic_id: str | None = None) -> str:
    """Classify intent - FAST rules first, LLM only for complex cases"""

    # Hard guard: booking keywords without explicit service -> book_general (avoid LLM guessing)
    has_price_kw = any(word in message.lower() for word in PRICE_WORDS)
    if _has_booking_keywords(message) and not has_price_kw and extract_service_type(message, clinic_id=clinic_id) is None and not any(
        phrase in message.lower()
        for phrase in BOOKING_INFO_PHRASES
    ):
        return INTENT_BOOK_GENERAL

    # FAST PATH: Try rules-based classification first (no API call!)
    rules_intent = classify_intent_rules(message, history, clinic_id=clinic_id)

    # If rules found a clear intent, use it immediately
    if rules_intent in [
        INTENT_GREETING,
        INTENT_THANKS,
        INTENT_INFO_HOURS,
        INTENT_INFO_CONTACT,
        INTENT_INFO_PRICES,
        INTENT_INFO_SERVICES,
        INTENT_CHECK_AVAILABILITY,
        INTENT_INFO_NAROCANJE,
        INTENT_HEALTH_SYMPTOMS,
    ]:
        return rules_intent

    # If rules found a booking intent, use it
    if rules_intent.startswith("book_") or rules_intent.startswith("info_"):
        return rules_intent

    # SLOW PATH: Only use LLM for ambiguous cases
    result = classify_intent_llm(message, history)

    intent = result.get("intent", "other")
    service = result.get("service")

    # Map to internal intent format
    if intent == "booking":
        if service and _service_mentioned_in_message(message, service):
            return f"book_{service}"
        return INTENT_BOOK_GENERAL
    elif intent == "health_advice":
        return INTENT_QUESTION  # Let it go through normal RAG flow
    elif intent == "question":
        return INTENT_QUESTION
    elif intent == INTENT_INFO_NAROCANJE:
        return INTENT_INFO_NAROCANJE
    elif intent == INTENT_INFO_SERVICES:
        return INTENT_INFO_SERVICES
    elif intent == INTENT_INFO_PRICES:
        return INTENT_INFO_PRICES
    elif intent == INTENT_INFO_CONTACT:
        return INTENT_INFO_CONTACT
    elif intent == INTENT_INFO_HOURS:
        return INTENT_INFO_HOURS
    elif intent == INTENT_GREETING:
        return INTENT_GREETING
    else:
        return INTENT_QUESTION


# Keep for backward compatibility - booking keywords
def _has_booking_keywords(message: str) -> bool:
    lowered = message.lower()
    return any(word in lowered for word in BOOKING_KEYWORDS)


def _looks_like_symptom_report(message: str) -> bool:
    """Heuristic: user reports symptoms (not asking informational question)."""
    lowered = message.lower()
    has_symptom = any(marker in lowered for marker in SYMPTOM_MARKERS)
    asks_question = any(marker in lowered for marker in QUESTION_MARKERS)
    return has_symptom and not asks_question


def _match_unsupported_symptom(message: str, clinic_id: str | None = None) -> dict[str, Any] | None:
    config = get_clinic_config(clinic_id=clinic_id) if clinic_id else get_clinic_config()
    entries = config.get("unsupported_symptoms", []) if isinstance(config, dict) else []
    if isinstance(entries, dict):
        entries = list(entries.values())
    if not isinstance(entries, list):
        return None
    lowered = message.lower()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        keywords = entry.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [keywords]
        if not isinstance(keywords, list):
            continue
        if any(str(kw).lower() in lowered for kw in keywords if kw):
            return entry
    return None


def _specialist_quick_replies(clinic_id: str | None = None) -> list[dict[str, str]]:
    """Build quick replies for primary specialists we can book immediately."""
    services = get_services(clinic_id=clinic_id)
    preferred = ["dermatolog", "ortoped", "okulist"]
    items: list[dict[str, str]] = []
    for key in preferred:
        info = services.get(key)
        if not isinstance(info, dict):
            continue
        name = str(info.get("name") or key).strip()
        items.append({"label": name, "value": key})
    return items


def _symptom_booking_nudge(service_key: str | None, clinic_id: str | None = None) -> str:
    """Short booking CTA appended after symptom guidance."""
    key = (service_key or "").strip().lower()
    if not key:
        return "Če želite, lahko preverim prost termin pri ustreznem specialistu."
    info = get_service_info(key)
    if info:
        return f"Če želite, lahko takoj preverim prost termin za {info['name'].lower()}."
    return "Če želite, lahko takoj preverim prost termin pri ustreznem specialistu."


def _append_nudge_if_missing(advice_text: str, nudge: str) -> str:
    """Avoid duplicated CTAs when advice template already includes booking prompt."""
    lowered = advice_text.lower()
    if ("termin" in lowered and ("preverim" in lowered or "naro" in lowered)):
        return advice_text
    return f"{advice_text}\n\n{nudge}"


# Old rule-based classify_intent kept as fallback
def classify_intent_rules(message: str, history: list = None, clinic_id: str | None = None) -> str:
    """Rule-based fallback for intent classification"""
    lowered = message.lower()
    services = get_services(clinic_id=clinic_id)
    service_map = get_service_map(clinic_id=clinic_id)

    # ===== HEALTH SYMPTOMS: Check FIRST before service keywords =====
    # Detect pain/symptom patterns like "pain in X" or "I have trouble with X"
    if any(pattern in lowered for pattern in SYMPTOM_PATTERNS):
        return INTENT_HEALTH_SYMPTOMS

    # Also check for standalone symptom keywords without booking intent
    has_symptom = any(word in lowered for word in SYMPTOM_WORDS)
    has_booking = any(word in lowered for word in BOOKING_KEYWORDS_EXTENDED)
    if has_symptom and not has_booking:
        return INTENT_HEALTH_SYMPTOMS

    # Info about booking process (should NOT start booking)
    if any(phrase in lowered for phrase in BOOKING_INFO_PHRASES):
        return INTENT_INFO_NAROCANJE

    # Availability checks should be handled explicitly
    if any(phrase in lowered for phrase in AVAILABILITY_PHRASES):
        return INTENT_CHECK_AVAILABILITY

    # Mixed intent: booking + price -> answer price info first
    has_price = any(word in lowered for word in PRICE_WORDS)
    has_booking_kw = any(word in lowered for word in BOOKING_KEYWORDS_EXTENDED)
    if has_price and has_booking_kw:
        return INTENT_INFO_PRICES

    # Appointment booking intents (with and without diacritics)
    if any(word in lowered for word in BOOKING_KEYWORDS_EXTENDED):
        # Check which service
        for service_key, variations in service_map.items():
            if any(var in lowered for var in variations):
                return f"book_{service_key}"
        return INTENT_BOOK_GENERAL

    # Working hours - check BEFORE availability because "kdaj ste odprti" contains "kdaj"
    if any(word in lowered for word in HOURS_WORDS):
        return INTENT_INFO_HOURS

    # Check available slots
    if any(word in lowered for word in AVAILABILITY_WORDS):
        return INTENT_CHECK_AVAILABILITY

    # Service information or booking (heuristic)
    for service_key in services.keys():
        if service_key in lowered or any(var in lowered for var in service_map.get(service_key, [])):
            # If user likely wants to book (no info/price question), start booking
            if "?" not in lowered and not any(tok in lowered for tok in SERVICE_INFO_TOKENS):
                return f"book_{service_key}"
            return f"info_{service_key}"

    # General service list
    if any(word in lowered for word in SERVICE_LIST_WORDS):
        return INTENT_INFO_SERVICES

    # Prices
    if any(word in lowered for word in PRICE_WORDS):
        return INTENT_INFO_PRICES

    # Team / leadership
    if any(word in lowered for word in TEAM_WORDS):
        return INTENT_INFO_TEAM

    # Contact / Location
    if any(word in lowered for word in CONTACT_WORDS):
        return INTENT_INFO_CONTACT

    # Thanks
    if any(word in lowered for word in THANKS_WORDS):
        return INTENT_THANKS

    # Greeting (with and without diacritics)
    if any(word in lowered for word in GREETING_WORDS):
        return INTENT_GREETING

    # Health symptoms → let RAG/knowledge base handle (has health info)
    # Don't intercept - return "question" so it goes through RAG
    return INTENT_QUESTION

def extract_date_from_message(message: str) -> Optional[str]:
    """Extract date from message (DD.MM[.YYYY] format)."""
    # Try DD.MM.YYYY or D.M.YYYY format
    match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', message)
    if match:
        day, month, year = match.groups()
        return f"{day.zfill(2)}.{month.zfill(2)}.{year}"

    # Try DD.MM or D.M format and infer year.
    # If inferred date in current year is already in the past, roll to next year.
    match = re.search(r'(?<!\d)(\d{1,2})\.(\d{1,2})(?!\d)', message)
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

    # Try relative dates like "jutri", "danes", "naslednji teden"
    lowered = message.lower()
    today = datetime.now()

    for token, offset in RELATIVE_DATES.items():
        if token in lowered:
            return (today + timedelta(days=offset)).strftime("%d.%m.%Y")

    return None

def extract_time_from_message(message: str) -> Optional[str]:
    """Extract time from message (HH:MM, HH-MM, or HHMM format)"""
    # Try HH:MM format
    match = re.search(r'(\d{1,2}):(\d{2})', message)
    if match:
        hour, minute = match.groups()
        return f"{hour.zfill(2)}:{minute}"

    # Try HH.MM format (e.g., "15.00")
    match = re.search(r'(\d{1,2})\.(\d{2})', message)
    if match:
        hour, minute = match.groups()
        return f"{hour.zfill(2)}:{minute}"

    # Try HH-MM format (e.g., "15-00")
    match = re.search(r'(\d{1,2})-(\d{2})', message)
    if match:
        hour, minute = match.groups()
        return f"{hour.zfill(2)}:{minute}"

    # Try HHMM format without separator (e.g., "1500")
    match = re.search(r'\b(\d{3,4})\b', message)
    if match:
        time_str = match.group(1)
        if len(time_str) == 4:
            hour, minute = time_str[:2], time_str[2:]
            return f"{hour}:{minute}"
        elif len(time_str) == 3:
            hour, minute = time_str[0], time_str[1:]
            return f"{hour.zfill(2)}:{minute}"

    # Try HH format (e.g., "ob 10")
    match = re.search(r'ob\s+(\d{1,2})', message.lower())
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
    # Allow single-word names (e.g., "Miha") but avoid symptoms/services
    single = parts[0].lower() if parts else ""
    if single in FULL_NAME_BLOCKED_SINGLE:
        return False
    return len(single) >= 3


def _short_contact_info() -> str:
    return get_response(INFO_CONTACT_SHORT)


def _service_price_info(service_type: Optional[str], clinic_id: str | None = None) -> str:
    info = get_service_info(service_type or "", clinic_id=clinic_id)
    if not info:
        return _get_info_response(INFO_KEY_PRICES, clinic_id=clinic_id)
    label = service_type or ""
    return get_response(
        "general.service_price",
        clinic_id=clinic_id,
        label=label.capitalize(),
        name=info["name"],
        price_range=info["price_range"],
        duration_minutes=info["duration_minutes"],
    )


def extract_service_type(message: str, clinic_id: str | None = None) -> Optional[str]:
    """Extract service type from message (router confidence + fallback matching)."""
    lowered = message.lower()
    service_map = get_service_map(clinic_id=clinic_id)

    # Primary path: use shared confidence detector (handles typos/synonyms/context).
    detected = detect_service_type_conf(lowered, service_map=service_map)
    if detected:
        return detected.lower()

    # Skip short keywords that cause false positives
    skip_keywords = SKIP_SERVICE_KEYWORDS

    for service_key, variations in service_map.items():
        for var in variations:
            # Skip problematic short keywords
            if var in skip_keywords:
                continue
            # Use word boundary to avoid substring matches
            if re.search(r'\b' + re.escape(var) + r'\b', lowered):
                return service_key

    return None

def detect_service_from_message(message: str, clinic_id: str | None = None) -> Optional[str]:
    """Backward-compatible alias for older call sites."""
    return extract_service_type(message, clinic_id=clinic_id)

BOOKING_FLOW_DEPS = BookingFlowDeps(
    get_appointment_state=get_appointment_state,
    reset_appointment_state=reset_appointment_state,
    reset_unified_state=reset_unified_state,
    reset_loop_count=conversation_tracker.reset_loop_count,
    set_step=lambda session_id, state, step: (
        state.__setitem__("step", step),
        StateManager(session_id).set_step(FlowStep(step)) if step in {s.value for s in FlowStep} else StateManager(session_id).set_step(None),
    ),
    set_appointment_field=lambda session_id, state, field, value: (
        state.__setitem__(field, value),
        StateManager(session_id).set_appointment_field(field, value),
    ),
    clear_appointment_data=lambda session_id, state: (
        reset_appointment_state(state),
        StateManager(session_id).clear_appointment_data(),
    ),
    is_negative=is_negative,
    is_affirmative=is_affirmative,
    is_likely_full_name=is_likely_full_name,
    extract_service_type=extract_service_type,
    extract_date_from_message=extract_date_from_message,
    extract_time_from_message=extract_time_from_message,
    validate_appointment_rules=validate_appointment_rules,
    get_available_time_slots=get_available_time_slots,
    get_service_info=get_service_info,
    format_appointment_summary=format_appointment_summary,
    reservation_service_cls=ReservationService,
    send_notifications_async=_send_reservation_emails_async,
    set_context_value=lambda session_id, key, value: StateManager(session_id).set_context_value(key, value),
)

INTERRUPT_FLOW_DEPS = InterruptFlowDeps(
    get_info_response=_get_info_response,
    service_price_info=_service_price_info,
    get_service_info=get_service_info,
)


def _booking_resume_prompt(step: str | None, state: dict[str, Any]) -> str:
    resume = build_resume_prompt(step)
    if resume:
        return resume
    return booking_get_resume_prompt(state, BOOKING_FLOW_DEPS)


BOOKING_INTERRUPT_DEPS = BookingInterruptDeps(
    is_in_flow=is_in_flow,
    get_current_step=get_current_step,
    get_appointment_data=get_appointment_data,
    get_context_value=lambda session_id, key, default=None: StateManager(session_id).get_context_value(key, default),
    set_context_value=lambda session_id, key, value: StateManager(session_id).set_context_value(key, value),
    extract_date_from_message=extract_date_from_message,
    extract_time_from_message=extract_time_from_message,
    extract_service_type=extract_service_type,
    is_likely_full_name=is_likely_full_name,
    build_interrupt_response=build_interrupt_response,
    build_resume_prompt=_booking_resume_prompt,
    interrupt_answer=lambda **kwargs: resolve_interrupt_answer(deps=INTERRUPT_FLOW_DEPS, **kwargs),
    get_info_response=_get_info_response,
    get_service_info=get_service_info,
    looks_like_symptom_report=_looks_like_symptom_report,
    symptom_advice=lambda message, service: (
        advice_only_headache()
        if any(k in message.lower() for k in ["glava", "glavobol", "migrena"])
        else advice_only(service)
    ),
)


def get_resume_prompt(state: dict) -> str:
    """Backward-compatible wrapper around extracted booking flow."""
    return booking_get_resume_prompt(state, BOOKING_FLOW_DEPS)


def handle_appointment_booking(message: str, session_id: str) -> str:
    """Backward-compatible wrapper around extracted booking flow."""
    return booking_handle_appointment_booking(message, session_id, BOOKING_FLOW_DEPS)


# ============================================================
# UNIFIED ROUTING SYSTEM - New architecture
# ============================================================

def handle_unified_routing(
    message: str,
    session_id: str,
    clinic_id: str | None = None,
) -> str | None:
    """
    Handle message using unified routing system.
    Returns response string, or None if should fall back to legacy system.
    """
    if clinic_id:
        set_current_clinic_id(clinic_id)
    appointment_state = get_appointment_state(session_id)
    state_mgr = StateManager(session_id)
    if clinic_id:
        state_mgr.set_context_value("clinic_id", clinic_id)
    state_mgr.set_context_value("clinic_id", clinic_id)
    unified_state = state_mgr.get_state()
    context = state_mgr.ensure_context()

    def _clear_booking_details_preserve_service() -> None:
        """Clear appointment details when changing service, keep only service type."""
        current_service = appointment_state.get("service_type")
        state_mgr.clear_appointment_data()
        if current_service:
            state_mgr.set_appointment_field("service_type", current_service)
        if appointment_state is not None:
            appointment_state["date"] = None
            appointment_state["time"] = None
            appointment_state["name"] = None
            appointment_state["phone"] = None
            appointment_state["email"] = None
            appointment_state["reason"] = None
            appointment_state["step"] = "date"

    # Handle pending service switch confirmation (DA/NE).
    pending_service_switch = context.get("pending_service_switch")
    if pending_service_switch and is_in_flow(session_id):
        pending_service_key = str(pending_service_switch).lower()
        pending_info = get_service_info(pending_service_key)

        if is_affirmative(message):
            state_mgr.confirm_service_switch(pending_service_key, legacy_state=appointment_state)
            state_mgr.clear_context_key("pending_service_switch")

            if pending_info:
                return get_response(
                    "booking.service_switch_confirmed",
                    clinic_id=clinic_id,
                    service_name=pending_info["name"],
                    duration_minutes=pending_info["duration_minutes"],
                    price_range=pending_info["price_range"],
                )
            return get_response("booking.service_switch_confirmed_noinfo", clinic_id=clinic_id)

        if is_negative(message):
            state_mgr.clear_context_key("pending_service_switch")
            step = appointment_state.get("step") or get_current_step(session_id)
            return build_resume_prompt(step) or get_response("booking.resume_prompt", clinic_id=clinic_id)

    # Follow-up path for unsupported symptoms (DA/NE -> specialist choice -> booking).
    awaiting_specialist_prompt = bool(context.get("awaiting_specialist_prompt"))
    awaiting_specialist_choice = bool(context.get("awaiting_specialist_choice"))
    if awaiting_specialist_prompt and not is_in_flow(session_id):
        service_choice = extract_service_type(message, clinic_id=clinic_id)
        if service_choice:
            state_mgr.clear_context_key("awaiting_specialist_prompt")
            state_mgr.clear_context_key("awaiting_specialist_choice")
            state_mgr.transition_to_booking(service_type=service_choice, legacy_state=appointment_state)
            start_flow(session_id, FlowType.APPOINTMENT, FlowStep.DATE)
            return get_response("booking.start_with_date", clinic_id=clinic_id, service_type=service_choice.lower())

        if is_affirmative(message):
            data = _specialist_quick_replies(clinic_id=clinic_id)
            if data:
                state_mgr.set_context_value("ui_override", {"type": "quick_replies", "data": data})
            state_mgr.clear_context_key("awaiting_specialist_prompt")
            state_mgr.set_context_value("awaiting_specialist_choice", True)
            return "Seveda. Pri katerem specialistu želite, da preverim termin?"

        if is_negative(message):
            state_mgr.clear_context_key("awaiting_specialist_prompt")
            return "V redu. Če si premislite, lahko napišete: ortoped, dermatolog ali okulist."

    if awaiting_specialist_choice and not is_in_flow(session_id):
        service_choice = extract_service_type(message, clinic_id=clinic_id)
        if service_choice:
            state_mgr.clear_context_key("awaiting_specialist_choice")
            state_mgr.transition_to_booking(service_type=service_choice, legacy_state=appointment_state)
            start_flow(session_id, FlowType.APPOINTMENT, FlowStep.DATE)
            return get_response("booking.start_with_date", clinic_id=clinic_id, service_type=service_choice.lower())
        if is_negative(message):
            state_mgr.clear_context_key("awaiting_specialist_choice")
            return "V redu. Če si premislite, sem tukaj."
        data = _specialist_quick_replies(clinic_id=clinic_id)
        if data:
            state_mgr.set_context_value("ui_override", {"type": "quick_replies", "data": data})
        return "Izberite specialista: dermatolog, ortoped ali okulist."

    # Keep unified state in sync with legacy appointment state.
    was_in_flow = is_in_flow(session_id)
    if appointment_state.get("step"):
        state_mgr.set_flow(FlowType.APPOINTMENT)
        step_val = appointment_state.get("step")
        try:
            state_mgr.set_step(FlowStep(step_val))
        except Exception:
            state_mgr.set_step(None)
    elif appointment_state.get("service_type") or was_in_flow:
        state_mgr.set_flow(FlowType.APPOINTMENT)
        if unified_state.get("step") is None:
            state_mgr.set_step(FlowStep.DATE)
    else:
        state_mgr.set_flow(FlowType.IDLE)
        state_mgr.set_step(None)

    decision = unified_route(message, unified_state)
    suggested_service = context.get("suggested_service")
    current_step = get_current_step(session_id)

    # If user provides a date after service info prompt, start booking immediately
    date_str = extract_date_from_message(message)
    if date_str and suggested_service:
        if not is_in_flow(session_id) or current_step in {FlowStep.SERVICE.value, "select_service", None}:
            state_mgr.transition_to_booking(service_type=suggested_service, legacy_state=appointment_state)
            start_flow(session_id, FlowType.APPOINTMENT, FlowStep.DATE)
            state_mgr.clear_context_key("suggested_service")
            return handle_appointment_booking(message, session_id)

    # Service step should accept classified service even if raw text is partial (e.g. "dermatolo").
    if (
        is_in_flow(session_id)
        and current_step in {FlowStep.SERVICE.value, "select_service", None}
        and decision.service_type
    ):
        state_mgr.transition_to_booking(service_type=decision.service_type, legacy_state=appointment_state)
        start_flow(session_id, FlowType.APPOINTMENT, FlowStep.DATE)
        state_mgr.set_context_value("suggested_service", decision.service_type)
        return handle_appointment_booking(message, session_id)

    # Log decision for debugging
    print(f"[UNIFIED] Intent: {decision.primary_intent.value}, Confidence: {decision.confidence:.2f}, Action: {decision.action.value}, Service: {decision.service_type}")

    policy_response = handle_booking_interrupt(
        message=message,
        session_id=session_id,
        decision_intent=decision.primary_intent,
        service_hint=decision.service_type or suggested_service,
        deps=BOOKING_INTERRUPT_DEPS,
    )
    if policy_response:
        return policy_response

    # Do not allow info/price detours while user is providing visit reason.
    if is_in_flow(session_id) and get_current_step(session_id) == FlowStep.REASON.value:
        if decision.primary_intent in {IntentType.INFO, IntentType.PRICE, IntentType.SERVICE_INFO}:
            return None

    # Handle AFFIRMATIVE/NEGATIVE in booking flow
    if decision.primary_intent == IntentType.AFFIRMATIVE and is_in_flow(session_id):
        step = get_current_step(session_id)
        if step == FlowStep.CONFIRM.value:
            # Complete booking
            appointment_data = get_appointment_data(session_id)
            if is_appointment_complete(session_id):
                # Use legacy booking completion
                return None  # Fall back to handle actual booking
        # Continue with next step
        return None  # Fall back to legacy for step handling

    # If user confirms after service info (no flow yet), start booking
    if decision.primary_intent == IntentType.AFFIRMATIVE and suggested_service and not is_in_flow(session_id):
        state_mgr.transition_to_booking(service_type=suggested_service, legacy_state=appointment_state)
        start_flow(session_id, FlowType.APPOINTMENT, FlowStep.DATE)
        state_mgr.clear_context_key("suggested_service")
        return handle_appointment_booking(message, session_id)

    if decision.primary_intent == IntentType.NEGATIVE and is_in_flow(session_id):
        reset_unified_state(session_id)
        return get_response("general.booking_cancelled", clinic_id=clinic_id)

    # Handle GREETING
    if decision.primary_intent == IntentType.GREETING:
        return get_response("general.greeting", clinic_id=clinic_id)

    # Handle GOODBYE
    if decision.primary_intent == IntentType.GOODBYE:
        return get_response("general.goodbye", clinic_id=clinic_id)

    # Handle BOOKING_APPOINTMENT intent
    if decision.primary_intent == IntentType.BOOKING_APPOINTMENT:
        if not is_in_flow(session_id):
            # Start new booking flow
            service_type = decision.service_type
            if service_type:
                state_mgr.transition_to_booking(service_type=service_type, legacy_state=appointment_state)
                start_flow(session_id, FlowType.APPOINTMENT, FlowStep.DATE)
                return get_response(
                    "booking.start_with_date",
                    clinic_id=clinic_id,
                    service_type=service_type.lower(),
                )
            else:
                state_mgr.transition_to_booking(service_type=None, legacy_state=appointment_state)
                start_flow(session_id, FlowType.APPOINTMENT, FlowStep.SERVICE)
                return get_response("booking.start_with_service", clinic_id=clinic_id)
        # Already in flow - fall back to legacy step handling
        return None

    # Handle URGENCY
    if decision.primary_intent == IntentType.URGENCY:
        return get_response("general.urgency", clinic_id=clinic_id)

    # Handle SERVICE_INFO (symptoms, service questions)
    if decision.primary_intent == IntentType.SERVICE_INFO:
        current_step = get_current_step(session_id)
        if is_in_flow(session_id) and current_step == FlowStep.REASON.value:
            return None
        if is_in_flow(session_id) and current_step in {FlowStep.SERVICE.value, "select_service"}:
            if extract_service_type(message, clinic_id=clinic_id):
                return None
        service = decision.service_type
        awaiting_price_service = bool(state_mgr.get_context_value("awaiting_price_service"))
        if service and awaiting_price_service:
            state_mgr.clear_context_key("awaiting_price_service")
            return _service_price_info(service.lower(), clinic_id=clinic_id)
        if service:
            state_mgr.set_context_value("suggested_service", service)
            if _looks_like_symptom_report(message):
                nudge = _symptom_booking_nudge(service, clinic_id=clinic_id)
                return _append_nudge_if_missing(advice_only(service), nudge)
        if _looks_like_symptom_report(message) and not service:
            lowered = message.lower()
            if any(k in lowered for k in ["glava", "glavobol", "migrena"]):
                return advice_only_headache()
            return _append_nudge_if_missing(
                advice_only(None),
                _symptom_booking_nudge(None, clinic_id=clinic_id),
            )
        if service == "DERMATOLOG":
            return get_response(INFO_SERVICE_DERMATOLOG, clinic_id=clinic_id)
        elif service == "ORTOPED":
            return get_response(INFO_SERVICE_ORTOPED, clinic_id=clinic_id)
        elif service == "OKULIST":
            return get_response(INFO_SERVICE_OKULIST, clinic_id=clinic_id)
        elif service == "ESTETSKI_POSEG":
            return get_response(INFO_SERVICE_ESTETSKI_POSEG, clinic_id=clinic_id)
        elif service == "LASERSKI_POSEG":
            return get_response(INFO_SERVICE_LASERSKI_POSEG, clinic_id=clinic_id)
        elif service == "FIZIOTERAPIJA":
            return get_response(INFO_SERVICE_FIZIOTERAPIJA, clinic_id=clinic_id)
        elif service == "KOZMETIKA":
            return get_response(INFO_SERVICE_KOZMETIKA, clinic_id=clinic_id)
        else:
            # General service info
            return _get_info_response(INFO_KEY_SERVICES, clinic_id=clinic_id)

    # Handle UNSUPPORTED_SYMPTOM (empathetic fallback)
    if decision.primary_intent == IntentType.UNSUPPORTED_SYMPTOM:
        unsupported = _match_unsupported_symptom(message, clinic_id=clinic_id)
        response_text = None
        if unsupported:
            raw_response = unsupported.get("response") or unsupported.get("message")
            if isinstance(raw_response, list):
                options = [str(item).strip() for item in raw_response if str(item).strip()]
                if options:
                    variant_id = str(unsupported.get("id") or "default")
                    counter_key = f"unsupported_response_variant:{variant_id}"
                    idx = int(state_mgr.get_context_value(counter_key, 0) or 0)
                    response_text = options[idx % len(options)]
                    state_mgr.set_context_value(counter_key, idx + 1)
            elif isinstance(raw_response, str):
                response_text = raw_response
        if not response_text:
            response_text = get_response("general.unsupported_symptom_default", clinic_id=clinic_id)
        if not is_in_flow(session_id):
            state_mgr.set_context_value("awaiting_specialist_prompt", True)
            state_mgr.clear_context_key("awaiting_specialist_choice")
        ui_override = unsupported.get("ui_override") if isinstance(unsupported, dict) else None
        if isinstance(ui_override, dict):
            state_mgr.set_context_value("ui_override", ui_override)
        else:
            quick_replies = None
            if isinstance(unsupported, dict):
                quick_replies = unsupported.get("quick_replies")
            if not quick_replies:
                quick_replies = get_domain_response(
                    "general",
                    "quick_replies_default",
                    default=None,
                    clinic_id=clinic_id,
                )
            data: list[dict[str, str]] = []
            if isinstance(quick_replies, list):
                for item in quick_replies:
                    if isinstance(item, dict):
                        label = str(item.get("label") or item.get("value") or "").strip()
                        value = str(item.get("value") or item.get("label") or "").strip()
                        if label and value:
                            data.append({"label": label, "value": value})
                    elif isinstance(item, str):
                        text = item.strip()
                        if text:
                            data.append({"label": text, "value": text})
            if data:
                state_mgr.set_context_value("ui_override", {"type": "quick_replies", "data": data})
        return response_text

    # Handle PRICE
    if decision.primary_intent == IntentType.PRICE:
        service = decision.service_type or suggested_service or appointment_state.get("service_type")
        last_booking = state_mgr.get_context_value("last_completed_booking", {}) or {}
        used_last_booking = False
        if not service and isinstance(last_booking, dict):
            remembered_service = last_booking.get("service_type")
            if remembered_service:
                service = str(remembered_service)
                used_last_booking = True
        if service:
            state_mgr.clear_context_key("awaiting_price_service")
            service_key = service.lower()
            reply = _service_price_info(service_key, clinic_id=clinic_id)
            if used_last_booking:
                date = str(last_booking.get("date") or "").strip()
                time = str(last_booking.get("time") or "").strip()
                if date and time:
                    reply = f"{reply}\n\nImate že termin {date} ob {time}."
            return reply
        state_mgr.set_context_value("awaiting_price_service", True)
        return _rag_info_answer(message, INFO_KEY_PRICES, clinic_id=clinic_id)

    # Handle INFO
    if decision.primary_intent == IntentType.INFO:
        lowered = message.lower()
        info_key = pick_info_key(message)
        if info_key == "cakalna_doba":
            service = decision.service_type or suggested_service or appointment_state.get("service_type")
            if service:
                return (
                    "Čakalna doba je odvisna od storitve in termina. "
                    f"Za {str(service).lower()} lahko takoj preverim prvi prost termin."
                )
            return (
                "Čakalna doba je odvisna od storitve. "
                "Napišite prosim kateri pregled želite (npr. dermatolog, ortoped, okulist), "
                "pa preverim prvi prost termin."
            )
        if info_key in CRITICAL_INFO_KEYS or info_key in INFO_KEYS_DIRECT:
            if info_key == INFO_KEY_CONTACT and any(k in lowered for k in CONTACT_ROUTE_WORDS):
                return _get_info_response(INFO_KEY_LOCATION, clinic_id=clinic_id)
            return _get_info_response(info_key, clinic_id=clinic_id)
        if info_key:
            return _rag_info_answer(message, info_key, clinic_id=clinic_id)
        return _rag_info_answer(message, INFO_KEY_SERVICES, clinic_id=clinic_id)

    # For other intents, fall back to legacy system
    return None


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Main chat endpoint (D4): unified router only, legacy path removed."""
    global conversation_history, last_interaction, chat_session_id

    message = request.message.strip()
    raw_session_id = request.session_id or chat_session_id
    strict_clinic = os.getenv("STRICT_CLINIC_ID", "false").strip().lower() in {"1", "true", "yes", "on"}
    try:
        clinic_id = resolve_clinic_id(request.clinic_id, strict=strict_clinic)
    except ValueError:
        available = list_available_clinics()
        raise HTTPException(status_code=400, detail={"error": "unknown_clinic_id", "available": available})

    token = set_current_clinic_id(clinic_id)
    try:
        session_id = f"{clinic_id}::{raw_session_id}"
        state_mgr = StateManager(session_id)

        if not message:
            payload = format_response(
                get_response("general.empty_message", clinic_id=clinic_id),
                state_manager=state_mgr,
                metadata={"contract_version": "v0.1", "router": "unified_only"},
            )
            return ChatResponse(reply=payload["text"], session_id=raw_session_id, metadata=payload["metadata"])

        # Session timeout hygiene
        now = datetime.now()
        if last_interaction and (now - last_interaction).total_seconds() > 3600:
            conversation_history = []
            if session_id in appointment_states:
                reset_appointment_state(appointment_states[session_id])
            reset_unified_state(session_id)
        last_interaction = now

        awaiting_price_service = bool(state_mgr.get_context_value("awaiting_price_service"))
        if awaiting_price_service:
            service_from_message = extract_service_type(message, clinic_id=clinic_id)
            if service_from_message:
                conversation_tracker.add_message(session_id, message)
                state_mgr.clear_context_key("awaiting_price_service")
                response_text = _service_price_info(service_from_message, clinic_id=clinic_id)
                if is_in_flow(session_id):
                    response_text = build_interrupt_response(
                        response_text,
                        get_current_step(session_id),
                        True,
                    )
                payload = format_response(
                    response_text,
                    state_manager=state_mgr,
                    metadata={
                        "contract_version": "v0.1",
                        "router": "unified_only",
                        "price_followup": True,
                    },
                )
                return ChatResponse(reply=payload["text"], session_id=raw_session_id, metadata=payload["metadata"])

        fast_pass = get_fast_pass_match(message, clinic_id=clinic_id)
        if fast_pass:
            fast_key = str(fast_pass.get("key") or "")
            if fast_key == INFO_KEY_PRICES and is_in_flow(session_id):
                unified_service = str(get_appointment_data(session_id).get("service_type") or "").strip()
                legacy_service = str(get_appointment_state(session_id).get("service_type") or "").strip()
                suggested_service = str(state_mgr.get_context_value("suggested_service") or "").strip()
                service_for_price = (unified_service or legacy_service or suggested_service).lower()

                if service_for_price:
                    conversation_tracker.add_message(session_id, message)
                    response_text = _service_price_info(service_for_price, clinic_id=clinic_id)
                    response_text = build_interrupt_response(
                        response_text,
                        get_current_step(session_id),
                        True,
                    )
                    payload = format_response(
                        response_text,
                        state_manager=state_mgr,
                        metadata={
                            "contract_version": "v0.1",
                            "router": "unified_only",
                            "fast_pass": True,
                            "category": fast_pass.get("category"),
                            "price_context_service": service_for_price,
                        },
                    )
                    return ChatResponse(reply=payload["text"], session_id=raw_session_id, metadata=payload["metadata"])

                state_mgr.set_context_value("awaiting_price_service", True)

            conversation_tracker.add_message(session_id, message)
            fast_reply = str(fast_pass.get("response", ""))
            if is_in_flow(session_id):
                fast_reply = build_interrupt_response(
                    fast_reply,
                    get_current_step(session_id),
                    True,
                )
            payload = format_response(
                fast_reply,
                state_manager=state_mgr,
                metadata={
                    "contract_version": "v0.1",
                    "router": "unified_only",
                    "fast_pass": True,
                    "category": fast_pass.get("category"),
                },
            )
            return ChatResponse(reply=payload["text"], session_id=raw_session_id, metadata=payload["metadata"])

        # Keep anti-loop guard for non-fast-pass traffic only.
        # While user is in booking flow, repeated inputs are often normal
        # (e.g., symptom restatement while awaiting date).
        in_booking_flow = is_in_flow(session_id)
        if (not in_booking_flow) and conversation_tracker.detect_loop(session_id, message):
            loop_count = conversation_tracker.get_loop_count(session_id)
            conversation_tracker.add_message(session_id, message)
            if loop_count >= 2:
                conversation_tracker.reset_loop_count(session_id)
                payload = format_response(
                    get_response("general.anti_loop.apology", clinic_id=clinic_id),
                    state_manager=state_mgr,
                    metadata={"contract_version": "v0.1", "router": "unified_only", "loop_guard": True},
                )
                return ChatResponse(reply=payload["text"], session_id=raw_session_id, metadata=payload["metadata"])
            payload = format_response(
                get_response("general.anti_loop.warning", clinic_id=clinic_id),
                state_manager=state_mgr,
                metadata={"contract_version": "v0.1", "router": "unified_only", "loop_guard": True},
            )
            return ChatResponse(reply=payload["text"], session_id=raw_session_id, metadata=payload["metadata"])

        conversation_tracker.add_message(session_id, message)

        # Primary path: unified routing handler
        response_text = handle_unified_routing(message, session_id, clinic_id=clinic_id)

        # If unified handler delegates booking step details
        if response_text is None and is_in_flow(session_id):
            response_text = handle_appointment_booking(message, session_id)

        # Final fallback (knowledge/general)
        if response_text is None:
            cached_response = response_cache.get(message)
            if cached_response:
                response_text = cached_response
            else:
                try:
                    if is_tourist_query(message):
                        response_text = answer_tourist_question(message)
                    else:
                        response_text = answer_with_hybrid_kb(
                            message,
                            history=conversation_history,
                            session_id=session_id,
                            clinic_id=clinic_id,
                        )
                    if len(response_text) > 50 and _get_uncertain_marker(clinic_id=clinic_id) not in response_text:
                        response_cache.set(message, response_text)
                except Exception as e:
                    print(f"[UNIFIED_FALLBACK] Error: {e}")
                    response_text = get_response("general.fallback_short", clinic_id=clinic_id)

        # Persist lightweight history + metadata
        conversation_history.append({"role": "user", "content": message})
        conversation_history.append({"role": "assistant", "content": response_text})
        last_user_message_by_session[session_id] = message
        if len(conversation_history) > 20:
            conversation_history = conversation_history[-20:]

        decision = unified_route(message, get_unified_state(session_id))
        metadata = {
            "contract_version": "v0.1",
            "router": "unified_only",
            "intent": decision.primary_intent.value,
            "confidence": round(float(decision.confidence), 3),
            "action": decision.action.value,
        }
        ui_override = state_mgr.get_context_value("ui_override")
        if ui_override:
            metadata["ui"] = ui_override

        try:
            flow_state = get_unified_state(session_id)
            appointment_state = get_appointment_state(session_id)
            current_step = appointment_state.get("step") if appointment_state.get("step") is not None else None
            metadata["flow"] = flow_state.get("flow")
            metadata["booking_step"] = current_step
        except Exception as e:
            print(f"[UI_CONTRACT] Failed to build UI payload: {e}")

        try:
            state = get_appointment_state(session_id)
            current_step = state.get("step") if state.get("step") is not None else None
            save_chat_message(
                session_id=session_id,
                role="user",
                content=message,
                intent=decision.primary_intent.value,
                booking_step=current_step,
                response_cached=False,
            )
            save_chat_message(
                session_id=session_id,
                role="assistant",
                content=response_text,
                booking_step=current_step,
                metadata=metadata,
            )
        except Exception as e:
            print(f"[CHAT_HISTORY] Failed to save conversation: {e}")

        payload = format_response(response_text, state_manager=state_mgr, metadata=metadata)
        if ui_override:
            state_mgr.clear_context_key("ui_override")
        return ChatResponse(reply=payload["text"], session_id=raw_session_id, metadata=payload["metadata"])
    finally:
        reset_current_clinic_id(token)


# ============================================================
# SMS WEBHOOK ENDPOINT - za Twilio incoming SMS
# ============================================================

from fastapi import Form, Response, UploadFile, File


# ============================================================
# VOICE INPUT ENDPOINT - Whisper transkripcija
# ============================================================

@router.post("/voice")
async def voice_input(
    file: UploadFile = File(...),
    session_id: str = None,
    clinic_id: str = None
):
    """
    Accepts a voice message, transcribes with Whisper, and returns a reply.

    Supported formats: mp3, mp4, mpeg, mpga, m4a, wav, webm, ogg
    Max size: 25 MB
    """
    from app.services.voice_service import get_voice_service

    voice_service = get_voice_service()

    # Check availability
    if not voice_service.is_available():
        return {
            "success": False,
            "error": get_response("general.voice_unavailable", clinic_id=clinic_id),
            "transcription": None,
            "reply": None
        }

    try:
        # Read file content
        content = await file.read()

        # Validate
        validation = voice_service.validate_audio_file(file.filename or "audio.wav", len(content))
        if not validation["valid"]:
            return {
                "success": False,
                "error": validation["error"],
                "transcription": None,
                "reply": None
            }

        # Transcribe
        result = await voice_service.transcribe_from_bytes(
            content,
            file.filename or "audio.wav"
        )

        if not result["success"]:
            return {
                "success": False,
                "error": result.get("error", get_response("general.voice_transcription_error", clinic_id=clinic_id)),
                "transcription": None,
                "reply": None
            }

        transcribed_text = result["text"]

        # Process transcribed text through chat
        from app.models.chat import ChatRequest
        chat_request = ChatRequest(
            message=transcribed_text,
            session_id=session_id,
            clinic_id=clinic_id,
        )

        # Use existing chat logic
        chat_response = await chat(chat_request)

        return {
            "success": True,
            "transcription": transcribed_text,
            "reply": chat_response.reply,
            "session_id": chat_response.session_id,
            "duration_seconds": result.get("duration_seconds")
        }

    except Exception as e:
        print(f"[VOICE] Error: {e}")
        return {
            "success": False,
            "error": get_response("general.voice_processing_error", clinic_id=clinic_id, error=str(e)),
            "transcription": None,
            "reply": None
        }


@router.post("/sms-webhook")
async def sms_webhook(
    From: str = Form(...),
    Body: str = Form(...),
    MessageSid: str = Form(default=""),
):
    """
    Twilio webhook - processes patient SMS responses to reminders.

    Patients can reply:
    - YES / OK → Confirm appointment
    - RESCHEDULE → Request a new time
    - CANCEL / NO → Cancel appointment

    Twilio Console:
    - Webhook URL: https://yourdomain.com/chat/sms-webhook
    - HTTP Method: POST
    """
    try:
        from app.services.reminder_scheduler import handle_sms_response
        from app.services.sms_service import send_sms

        print(f"[SMS WEBHOOK] Received from {From}: {Body} (SID: {MessageSid})")

        # Procesiraj odgovor
        result = handle_sms_response(From, Body)

        # Send reply to patient
        if result.get("response_message"):
            send_sms(From, result["response_message"])

        # Twilio TwiML response (empty - no outbound SMS via TwiML)
        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
        return Response(content=twiml, media_type="application/xml")

    except Exception as e:
        print(f"[SMS WEBHOOK] Error: {e}")
        # Return empty response on error
        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
        return Response(content=twiml, media_type="application/xml")
