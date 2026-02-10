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
from app.services.routing.nlp_utils import is_affirmative, is_negative
from app.services.routing.state_manager import ConversationTracker, SimpleCache
from app.services.routing.intent_engine import classify_intent_llm
from app.services.routing.interrupt_handler import build_interrupt_response, build_resume_prompt
from app.services.routing.advice import advice_only, advice_only_headache
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
USE_FULL_KB_LLM = False  # False = RAG (hitro), True = full KB (počasno)
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
def _get_info_response(key: str, clinic_id: str | None = None) -> str:
    return clinic_get_info_response(key, "Kako vam lahko pomagam?", clinic_id=clinic_id)


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
        return f"{snippet}\n\nVeč informacij: {best.url}"
    return snippet

# Kritični ključi
BOOKING_RELEVANT_KEYS = {"dermatolog", "ortoped", "okulist", "laserski_poseg", "estetski_poseg", "kozmetika", "storitve", "prosti_termini"}
CRITICAL_INFO_KEYS = {
    "delovni_cas", "kontakt", "cene", "storitve", "prosti_termini",
    "dermatolog", "ortoped", "okulist", "laserski_poseg", "estetski_poseg", "kozmetika"
}

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
    service_keywords = {
        "ortoped": ["ortoped", "ortopedski", "ortopedija"],
        "dermatolog": ["dermatolog", "dermatološki", "dermatologija"],
        "okulist": ["okulist", "okulistični", "oftalmolog", "očesni"],  # Removed "oči" - too short, matches "naročil"
        "kozmetika": ["kozmetik", "kozmetični"],
        "estetski_poseg": ["estetski", "botox", "filer"],
        "laserski_poseg": ["laser", "laserski"],
    }
    keywords = service_keywords.get(service, [])
    # Use word boundary matching to avoid substring issues
    for kw in keywords:
        if re.search(r'\b' + re.escape(kw), lowered):
            return True
    return False


def classify_intent(message: str, history: list = None, clinic_id: str | None = None) -> str:
    """Classify intent - FAST rules first, LLM only for complex cases"""

    # Hard guard: booking keywords without explicit service -> book_general (avoid LLM guessing)
    has_price_kw = any(word in message.lower() for word in ["cena", "cene", "cenik", "koliko", "stane"])
    if _has_booking_keywords(message) and not has_price_kw and extract_service_type(message, clinic_id=clinic_id) is None and not any(
        phrase in message.lower()
        for phrase in [
            "kako se naročim", "kako se narocim", "kako poteka naročanje", "kako poteka narocanje",
            "kako rezerviram", "kako rezervirati", "kako do termina", "kako pridem do termina",
        ]
    ):
        return "book_general"

    # FAST PATH: Try rules-based classification first (no API call!)
    rules_intent = classify_intent_rules(message, history, clinic_id=clinic_id)

    # If rules found a clear intent, use it immediately
    if rules_intent in ["greeting", "thanks", "info_hours", "info_contact", "info_prices",
                        "info_services", "check_availability", "info_narocanje",
                        "health_symptoms"]:
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
        return "book_general"
    elif intent == "health_advice":
        return "question"  # Let it go through normal RAG flow
    elif intent == "question":
        return "question"
    elif intent == "info_narocanje":
        return "info_narocanje"
    elif intent == "info_services":
        return "info_services"
    elif intent == "info_prices":
        return "info_prices"
    elif intent == "info_contact":
        return "info_contact"
    elif intent == "info_hours":
        return "info_hours"
    elif intent == "greeting":
        return "greeting"
    else:
        return "question"


# Keep for backward compatibility - booking keywords
def _has_booking_keywords(message: str) -> bool:
    lowered = message.lower()
    return any(word in lowered for word in [
        "naroči", "naročilo", "naroci", "narocilo", "termin", "rezerv",
        "naročil", "naročila", "narocil", "narocila",
        "rad bi", "rada bi", "bi rad", "bi rada",
        "želel", "želela", "zelim", "želim",
        "hočem", "hocem",
    ])


def _looks_like_symptom_report(message: str) -> bool:
    """Heuristic: user reports symptoms (not asking informational question)."""
    lowered = message.lower()
    symptom_markers = [
        "boli",
        "boleč",
        "bolec",
        "bolečin",
        "bolecin",
        "težav",
        "tezav",
        "srbi",
        "izpuščaj",
        "izpuscaj",
        "otekl",
        "slabo vidim",
        "imam",
        "me ",
    ]
    question_markers = ["?", "kaj", "kako", "kateri", "katere", "koliko", "kdaj", "kje", "ali "]
    has_symptom = any(marker in lowered for marker in symptom_markers)
    asks_question = any(marker in lowered for marker in question_markers)
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


# Old rule-based classify_intent kept as fallback
def classify_intent_rules(message: str, history: list = None, clinic_id: str | None = None) -> str:
    """Rule-based fallback for intent classification"""
    lowered = message.lower()
    services = get_services(clinic_id=clinic_id)
    service_map = get_service_map(clinic_id=clinic_id)

    # ===== HEALTH SYMPTOMS: Check FIRST before service keywords =====
    # Detect pain/symptom patterns like "boli me X", "imam težave z X", "boli X"
    symptom_patterns = ["boli me", "boli mi", "imam težave", "imam tezave", "me boli", "mi boli",
                        "bolečine v", "bolecine v", "srbečica", "srbecica", "otekl", "izpuščaj",
                        "srbi", "srbi me", "srbeče", "srbeco", "znamenje", "kožno znamenje", "kozni madez",
                        "kožni madež", "glavobol", "migrena", "omotica"]
    if any(pattern in lowered for pattern in symptom_patterns):
        return "health_symptoms"

    # Also check for standalone symptom keywords without booking intent
    symptom_words = ["boli", "bolec", "boleč", "bolečin", "težav", "simptom", "srbi", "srbe", "srbeč", "srbec",
                     "izpuščaj", "izpuscaj", "znamenje", "madež", "madez", "koža", "koza",
                     "glavobol", "migrena", "omotica"]
    has_symptom = any(word in lowered for word in symptom_words)
    has_booking = any(word in lowered for word in ["naroči", "termin", "rezerv", "želim naročiti"])
    if has_symptom and not has_booking:
        return "health_symptoms"

    # Info about booking process (should NOT start booking)
    if any(phrase in lowered for phrase in [
        "kako se naročim", "kako se narocim", "kako poteka naročanje", "kako poteka narocanje",
        "kako rezerviram", "kako rezervirati", "kako do termina", "kako pridem do termina"
    ]):
        return "info_narocanje"

    # Availability checks should be handled explicitly
    if any(phrase in lowered for phrase in ["proste termine", "prosti termini", "razpoložljivi termini", "razpolozljivi termini"]):
        return "check_availability"

    # Mixed intent: booking + price -> answer price info first
    has_price = any(word in lowered for word in ["cena", "cene", "cenik", "koliko", "stane"])
    has_booking_kw = any(word in lowered for word in [
        "naroči", "naročilo", "naroci", "narocilo", "termin", "rezerv",
        "želim", "zelim", "potrebujem", "rad bi", "rada bi", "bi rad", "bi rada",
        "naročil", "naročila", "narocil", "narocila", "hočem", "hocem", "želel", "želela"
    ])
    if has_price and has_booking_kw:
        return "info_prices"

    # Appointment booking intents (with and without diacritics)
    if any(word in lowered for word in [
        "naroči", "naročilo", "naroci", "narocilo", "termin", "rezerv",
        "želim", "zelim", "potrebujem", "rad bi", "rada bi", "bi rad", "bi rada",
        "naročil", "naročila", "narocil", "narocila", "hočem", "hocem", "želel", "želela"
    ]):
        # Check which service
        for service_key, variations in service_map.items():
            if any(var in lowered for var in variations):
                return f"book_{service_key}"
        return "book_general"

    # Working hours - check BEFORE availability because "kdaj ste odprti" contains "kdaj"
    if any(word in lowered for word in ["delovni čas", "delovni cas", "odprto", "odprti", "kdaj ste odprti", "do kdaj", "od kdaj"]):
        return "info_hours"

    # Check available slots
    if any(word in lowered for word in ["prost", "razpoložljiv", "razpolozljiv", "kdaj", "termin"]):
        return "check_availability"

    # Service information or booking (heuristic)
    for service_key in services.keys():
        if service_key in lowered or any(var in lowered for var in service_map.get(service_key, [])):
            # If user likely wants to book (no info/price question), start booking
            info_tokens = ["cena", "cene", "koliko", "stane", "opis", "kaj", "ponudba", "storitve", "kakšne", "kaksne"]
            if "?" not in lowered and not any(tok in lowered for tok in info_tokens):
                return f"book_{service_key}"
            return f"info_{service_key}"

    # General service list
    if any(word in lowered for word in ["storitve", "pregled", "ponudba", "kaj ponujate"]):
        return "info_services"

    # Prices
    if any(word in lowered for word in ["cena", "cene", "cenik", "koliko", "stane"]):
        return "info_prices"

    # Team / leadership
    if any(word in lowered for word in ["šef", "sef", "vodja", "vodstvo", "direktor", "kdo vodi", "kdo je glavni", "ekipa", "zdravniki", "kdo dela pri vas"]):
        return "info_ekipa"

    # Contact / Location
    if any(word in lowered for word in ["kontakt", "telefon", "email", "naslov", "lokacija", "nahaja", "kje ste", "kje se", "naslovom", "pridi", "pridem", "parkir", "parking", "parkiri"]):
        return "info_contact"

    # Thanks
    if any(word in lowered for word in ["hvala", "najlepša hvala", "hvala lepa", "thanks", "thx"]):
        return "thanks"

    # Greeting (with and without diacritics)
    if any(word in lowered for word in ["pozdravljeni", "živjo", "zivjo", "dober dan", "zdravo", "hej", "halo", "bok"]):
        return "greeting"

    # Health symptoms → let RAG/knowledge base handle (has health info)
    # Don't intercept - return "question" so it goes through RAG
    return "question"

def extract_date_from_message(message: str) -> Optional[str]:
    """Extract date from message (DD.MM.YYYY format)"""
    # Try DD.MM.YYYY or D.M.YYYY format
    match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', message)
    if match:
        day, month, year = match.groups()
        return f"{day.zfill(2)}.{month.zfill(2)}.{year}"

    # Try relative dates like "jutri", "danes", "naslednji teden"
    lowered = message.lower()
    today = datetime.now()

    if "danes" in lowered:
        return today.strftime("%d.%m.%Y")
    if "jutri" in lowered:
        return (today + timedelta(days=1)).strftime("%d.%m.%Y")
    if "pojutrišnjem" in lowered:
        return (today + timedelta(days=2)).strftime("%d.%m.%Y")

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
    blocked_tokens = [
        "koliko",
        "stane",
        "cena",
        "cenik",
        "parking",
        "park",
        "kako",
        "kje",
        "kontakt",
        "ura",
        "termin",
        "pregled",
        "storitev",
        "delate",
        "sobota",
        "nedelja",
    ]
    if any(token in lowered for token in blocked_tokens):
        return False
    if any(char.isdigit() for char in stripped):
        return False
    parts = [p for p in stripped.split() if p]
    if len(parts) >= 2:
        return True
    # Allow single-word names (e.g., "Miha") but avoid symptoms/services
    single = parts[0].lower() if parts else ""
    blocked_single = [
        "koleno", "hrbet", "glava", "izpuščaj", "izpuscaj", "znamenje", "koža", "koza",
        "bolečina", "bolečine", "bolecina", "bolecine", "srbi", "srbe", "srbeč", "srbec",
        "dermatološki", "ortopedski", "okulistični", "okulisticni", "laser", "laserski",
        "estetski", "kozmetični", "kozmeticni", "pregled", "termin",
    ]
    if single in blocked_single:
        return False
    return len(single) >= 3


def _short_contact_info() -> str:
    return (
        "🚗 Parking: brezplačen pred objektom\n"
        "📞 Telefon: 01 234 56 78\n"
        "📧 Email: info@zdravstveni-center.si"
    )


def _service_price_info(service_type: Optional[str], clinic_id: str | None = None) -> str:
    info = get_service_info(service_type or "", clinic_id=clinic_id)
    if not info:
        return _get_info_response("cene", clinic_id=clinic_id)
    label = service_type or ""
    return f"💰 {label.capitalize()} – {info['name']}: Cena {info['price_range']} · {info['duration_minutes']} min"


def extract_service_type(message: str, clinic_id: str | None = None) -> Optional[str]:
    """Extract service type from message using word boundary matching"""
    import re
    lowered = message.lower()
    service_map = get_service_map(clinic_id=clinic_id)

    # Skip short keywords that cause false positives
    skip_keywords = {"oči", "oci"}  # "oči" matches "naročil"

    for service_key, variations in service_map.items():
        for var in variations:
            # Skip problematic short keywords
            if var in skip_keywords:
                continue
            # Use word boundary to avoid substring matches
            if re.search(r'\b' + re.escape(var), lowered):
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
                return (
                    f"Super, preklopim na **{pending_info['name']}**.\n\n"
                    f"📋 Trajanje: {pending_info['duration_minutes']} minut\n"
                    f"💰 Cena: {pending_info['price_range']}\n\n"
                    "Kateri datum vas zanima? (npr. 15.3.2026)"
                )
            return "Super, preklopim storitev. Kateri datum vas zanima? (npr. 15.3.2026)"

        if is_negative(message):
            state_mgr.clear_context_key("pending_service_switch")
            step = appointment_state.get("step") or get_current_step(session_id)
            return build_resume_prompt(step) or "V redu, nadaljujemo z naročilom."

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

    # If user provides a date after service info prompt, start booking immediately
    date_str = extract_date_from_message(message)
    if date_str and suggested_service and not is_in_flow(session_id):
        state_mgr.transition_to_booking(service_type=suggested_service, legacy_state=appointment_state)
        start_flow(session_id, FlowType.APPOINTMENT, FlowStep.DATE)
        state_mgr.clear_context_key("suggested_service")
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
        return "V redu, naročilo preklicano. Kako vam lahko drugače pomagam?"

    # Handle GREETING
    if decision.primary_intent == IntentType.GREETING:
        return _get_info_response("pozdrav", clinic_id=clinic_id)

    # Handle GOODBYE
    if decision.primary_intent == IntentType.GOODBYE:
        return _get_info_response("hvala", clinic_id=clinic_id)

    # Handle BOOKING_APPOINTMENT intent
    if decision.primary_intent == IntentType.BOOKING_APPOINTMENT:
        if not is_in_flow(session_id):
            # Start new booking flow
            service_type = decision.service_type
            if service_type:
                state_mgr.transition_to_booking(service_type=service_type, legacy_state=appointment_state)
                start_flow(session_id, FlowType.APPOINTMENT, FlowStep.DATE)
                return f"Odlično! Naročilo za {service_type.lower()}. Kateri datum vam ustreza? (npr. 15.2.2026)"
            else:
                state_mgr.transition_to_booking(service_type=None, legacy_state=appointment_state)
                start_flow(session_id, FlowType.APPOINTMENT, FlowStep.SERVICE)
                return "Na kateri pregled se želite naročiti?\n\n- Dermatolog\n- Ortoped\n- Okulist\n- Laserski poseg\n- Estetski poseg\n- Kozmetika"
        # Already in flow - fall back to legacy step handling
        return None

    # Handle URGENCY
    if decision.primary_intent == IntentType.URGENCY:
        return """⚠️ **Če gre za nujni primer, prosim pokličite:**
- Urgenca: 112
- Zdravstveni center: 01 234 56 78

Za nujne primere nudimo prednostne termine. Želite, da preverim najhitrejši prosti termin?"""

    # Handle SERVICE_INFO (symptoms, service questions)
    if decision.primary_intent == IntentType.SERVICE_INFO:
        if is_in_flow(session_id) and get_current_step(session_id) == "reason":
            return None
        service = decision.service_type
        if service:
            state_mgr.set_context_value("suggested_service", service)
            if _looks_like_symptom_report(message):
                return advice_only(service)
        if _looks_like_symptom_report(message) and not service:
            lowered = message.lower()
            if any(k in lowered for k in ["glava", "glavobol", "migrena"]):
                return advice_only_headache()
            return advice_only(None)
        if service == "DERMATOLOG":
            return """**Dermatologija** - pregledi kožnih težav

Zdravimo:
- Izpuščaje, akne, ekceme
- Luskavico, psoriaze
- Kožne spremembe, madeže
- Glivične okužbe

🔬 **Dermatološki pregled** (30 min, 25-150 €)

🎯 Želite termin? Povejte mi datum!"""
        elif service == "ORTOPED":
            return """**Ortopedija** - pregledi gibalnega sistema

Zdravimo:
- Bolečine v hrbtu, kolenih, ramenih
- Športne poškodbe
- Težave s sklepi
- Poškodbe mišic in vezi

🦴 **Ortopedski pregled** (30 min, 40-80 €)

🎯 Želite termin? Povejte mi datum!"""
        elif service == "OKULIST":
            return """**Oftalmologija** - pregledi oči

Zdravimo:
- Težave z vidom
- Očesne bolezni
- Predpis očal in kontaktnih leč

👁️ **Očesni pregled** (30 min, 35-70 €)

🎯 Želite termin? Povejte mi datum!"""
        elif service == "ESTETSKI_POSEG":
            return """**Estetski posegi**

Ponujamo:
- Botox
- Fillerji
- Biorevitalizacija kože

💉 **Estetski poseg** (30 min, 80-300 €)

🎯 Želite termin? Povejte mi datum!"""
        elif service == "LASERSKI_POSEG":
            return """**Laserski posegi**

Ponujamo:
- Odstranjevanje žilic
- Odstranjevanje bradavic
- Zdravljenje glivic nohtov

⚡ **Laserski poseg** (30 min, 50-200 €)

🎯 Želite termin? Povejte mi datum!"""
        elif service == "FIZIOTERAPIJA":
            return """**Fizioterapija**

Ponujamo:
- Rehabilitacija po poškodbah
- Masaže
- Razgibalne vaje

💆 **Fizioterapija** (60 min, 40-80 €)

🎯 Želite termin? Povejte mi datum!"""
        elif service == "KOZMETIKA":
            return """**Kozmetični salon**

Ponujamo:
- Profesionalna nega obraza
- Tretmaji kože
- Kozmetični posegi

✨ **Kozmetični tretma** (60 min, 40-100 €)

🎯 Želite termin? Povejte mi datum!"""
        else:
            # General service info
            return _get_info_response("storitve", clinic_id=clinic_id)

    # Handle UNSUPPORTED_SYMPTOM (empathetic fallback)
    if decision.primary_intent == IntentType.UNSUPPORTED_SYMPTOM:
        unsupported = _match_unsupported_symptom(message, clinic_id=clinic_id)
        response_text = None
        if unsupported:
            response_text = unsupported.get("response") or unsupported.get("message")
        if not response_text:
            response_text = (
                "Žal mi je, da imate težave. V našem centru nimamo ustreznega specialista, "
                "lahko pa ponudimo splošni posvet. Želite, da preverim proste termine?"
            )
        ui_override = unsupported.get("ui_override") if isinstance(unsupported, dict) else None
        if isinstance(ui_override, dict):
            state_mgr.set_context_value("ui_override", ui_override)
        else:
            quick_replies = None
            if isinstance(unsupported, dict):
                quick_replies = unsupported.get("quick_replies")
            if not quick_replies:
                quick_replies = [
                    {"label": "Da, prosim", "value": "DA"},
                    {"label": "Ne, hvala", "value": "NE"},
                ]
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
        if service:
            service_key = service.lower()
            return _service_price_info(service_key, clinic_id=clinic_id)
        return _rag_info_answer(message, "cene", clinic_id=clinic_id)

    # Handle INFO
    if decision.primary_intent == IntentType.INFO:
        lowered = message.lower()
        info_key = pick_info_key(message)
        if info_key in CRITICAL_INFO_KEYS or info_key in {"parkiranje", "delovni_cas", "lokacija", "kontakt"}:
            if info_key == "kontakt" and any(k in lowered for k in ["pridem", "pridemo", "pot"]):
                return _get_info_response("lokacija", clinic_id=clinic_id)
            return _get_info_response(info_key, clinic_id=clinic_id)
        if info_key:
            return _rag_info_answer(message, info_key, clinic_id=clinic_id)
        return _rag_info_answer(message, "storitve", clinic_id=clinic_id)

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
                "Prosim napišite sporočilo, da vam lahko pomagam.",
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

        # Keep anti-loop guard (unified mode only)
        if conversation_tracker.detect_loop(session_id, message):
            loop_count = conversation_tracker.get_loop_count(session_id)
            conversation_tracker.add_message(session_id, message)
            if loop_count >= 2:
                conversation_tracker.reset_loop_count(session_id)
                payload = format_response(
                    "Mislim, da je prišlo do nesporazuma. Začniva znova. Kako vam lahko pomagam?",
                    state_manager=state_mgr,
                    metadata={"contract_version": "v0.1", "router": "unified_only", "loop_guard": True},
                )
                return ChatResponse(reply=payload["text"], session_id=raw_session_id, metadata=payload["metadata"])
            payload = format_response(
                "Opazil sem ponavljanje. Prosim povejte konkretno: pregled + datum.",
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
                    if len(response_text) > 50 and "Nisem prepričan" not in response_text:
                        response_cache.set(message, response_text)
                except Exception as e:
                    print(f"[UNIFIED_FALLBACK] Error: {e}")
                    response_text = "Lahko pomagam z naročilom, cenami, lokacijo in termini."

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
    Sprejme glasovno sporočilo, transkribira z Whisper in vrne odgovor.

    Podprti formati: mp3, mp4, mpeg, mpga, m4a, wav, webm, ogg
    Maksimalna velikost: 25 MB

    Returns:
        {
            "transcription": str,
            "reply": str,
            "session_id": str
        }
    """
    from app.services.voice_service import get_voice_service

    voice_service = get_voice_service()

    # Check availability
    if not voice_service.is_available():
        return {
            "success": False,
            "error": "Voice service ni na voljo. Prosimo pišite sporočilo.",
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
                "error": result.get("error", "Napaka pri transkripciji"),
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
            "error": f"Napaka pri obdelavi: {str(e)}",
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
    Webhook za Twilio - procesira odgovore pacientov na SMS opomnike.

    Pacienti lahko odgovorijo:
    - DA / PRIDEM / OK → Potrditev termina
    - PRESTAVI → Želim nov termin
    - ODPOVEJ / NE → Preklic termina

    Uporaba v Twilio Console:
    - Webhook URL: https://yourdomain.com/chat/sms-webhook
    - HTTP Method: POST
    """
    try:
        from app.services.reminder_scheduler import handle_sms_response
        from app.services.sms_service import send_sms

        print(f"[SMS WEBHOOK] Received from {From}: {Body} (SID: {MessageSid})")

        # Procesiraj odgovor
        result = handle_sms_response(From, Body)

        # Pošlji odgovor pacientu
        if result.get("response_message"):
            send_sms(From, result["response_message"])

        # Twilio TwiML response (prazen - ne pošiljamo novega SMS-a preko TwiML)
        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
        return Response(content=twiml, media_type="application/xml")

    except Exception as e:
        print(f"[SMS WEBHOOK] Error: {e}")
        # Return empty response on error
        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
        return Response(content=twiml, media_type="application/xml")
