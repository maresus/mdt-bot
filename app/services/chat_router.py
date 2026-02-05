import re
import random
import json
import os
import hashlib
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Any, Optional, Tuple
import uuid
import threading

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

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
    SERVICES,
    SERVICE_NAME_MAP,
)
from app.rag.rag_engine import rag_engine
from app.rag.knowledge_base import (
    CONTACT,
    generate_llm_answer,
    search_knowledge,
)
from app.core.config import Settings
from app.core.llm_client import get_llm_client
from app.rag.chroma_service import answer_tourist_question, is_tourist_query
from app.services.router_agent import route_message
from app.services.executor_v2 import execute_decision
from app.services.chat_history_service import get_chat_history_service
from app.services import knowledge_base as kb_module

# Unified Routing System imports
from app.services.session.unified_state import (
    get_unified_state,
    reset_unified_state,
    is_in_flow,
    get_current_step,
    start_flow,
    advance_step,
    set_appointment_field,
    get_appointment_data,
    is_appointment_complete,
    FlowType,
    FlowStep,
)
from app.services.routing.unified_router import route as unified_route, IntentType
from app.services.routing.confidence import SwitchAction, detect_service_type as unified_detect_service
from app.services.routing.interrupt_handler import build_interrupt_response, build_resume_prompt
from app.core.response_formatter import format_response
from app.services.flows.booking_flow import (
    BookingFlowDeps,
    get_resume_prompt as booking_get_resume_prompt,
    handle_appointment_booking as booking_handle_appointment_booking,
)
from app.services.flows.info_flow import pick_info_key
from app.services.flows.interrupt_flow import InterruptFlowDeps, resolve_interrupt_answer

router = APIRouter(prefix="/chat", tags=["chat"])
USE_ROUTER_V2 = True
USE_FULL_KB_LLM = False  # False = RAG (hitro), True = full KB (počasno)
# D4: legacy kill - unified router is always enabled.
USE_UNIFIED_ROUTER = True
SHORT_MODE = os.getenv("SHORT_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}

# ========== ANTI-LOOP & CACHE MECHANISMS ==========

# Slovenian stop words - ignore these in loop detection
STOP_WORDS = {
    "je", "in", "za", "na", "se", "so", "ali", "kako", "kdaj", "kje", "kaj", "katere",
    "kateri", "kakšen", "kakšna", "ima", "imate", "imajo", "bi", "bo", "bom", "boste",
    "ste", "sem", "smo", "si", "lahko", "tudi", "mi", "te", "me", "ga", "jo", "jim",
    "iz", "do", "pri", "od", "po", "ta", "te", "to", "ta", "ti", "teh", "tem",
    "a", "ali", "ampak", "vendar", "ker", "če", "ko", "da", "ki"
}

class ConversationTracker:
    """Track recent questions to detect loops with stop word filtering"""
    def __init__(self):
        self.recent_messages: dict[str, list[str]] = {}  # session_id -> [messages]
        self.loop_count: dict[str, int] = {}  # session_id -> count

    def _tokenize_meaningful(self, message: str) -> set[str]:
        """Extract meaningful tokens (remove stop words and punctuation)"""
        # Remove punctuation and lowercase
        cleaned = re.sub(r'[^\w\s]', '', message.lower())
        tokens = cleaned.split()
        # Filter out stop words and very short tokens
        meaningful = {t for t in tokens if len(t) > 2 and t not in STOP_WORDS}
        return meaningful

    def add_message(self, session_id: str, message: str):
        """Add message to tracking"""
        if session_id not in self.recent_messages:
            self.recent_messages[session_id] = []
        self.recent_messages[session_id].append(message.lower().strip())
        # Keep only last 3
        if len(self.recent_messages[session_id]) > 3:
            self.recent_messages[session_id].pop(0)

    def detect_loop(self, session_id: str, message: str) -> bool:
        """Detect if message is repeating (improved with stop word filtering)"""
        if session_id not in self.recent_messages:
            return False

        recent = self.recent_messages.get(session_id, [])
        if len(recent) < 2:
            return False

        # Get meaningful tokens from current message
        msg_tokens = self._tokenize_meaningful(message)

        # Need at least 2 meaningful tokens to check
        if len(msg_tokens) < 2:
            return False

        # Check similarity with last 2-3 messages
        for prev_msg in recent[-3:]:
            prev_tokens = self._tokenize_meaningful(prev_msg)

            if len(prev_tokens) < 2:
                continue

            # Calculate overlap
            overlap = msg_tokens & prev_tokens
            overlap_ratio = len(overlap) / len(msg_tokens)

            # STRICT: Need 85%+ overlap AND at least 2 shared tokens
            if overlap_ratio > 0.85 and len(overlap) >= 2:
                self.loop_count[session_id] = self.loop_count.get(session_id, 0) + 1
                return True

        # Reset loop count if no loop detected
        self.loop_count[session_id] = 0
        return False

    def get_loop_count(self, session_id: str) -> int:
        """Get current loop count"""
        return self.loop_count.get(session_id, 0)

    def reset_loop_count(self, session_id: str):
        """Reset loop counter"""
        self.loop_count[session_id] = 0


class SimpleCache:
    """Simple in-memory cache for LLM responses"""
    def __init__(self, ttl_seconds: int = 86400):  # 24h default
        self.cache: dict[str, tuple[str, datetime]] = {}
        self.ttl = timedelta(seconds=ttl_seconds)

    def get(self, query: str, context: str = "") -> Optional[str]:
        """Get cached response"""
        key = self._hash_key(query, context)
        if key in self.cache:
            response, timestamp = self.cache[key]
            if datetime.now() - timestamp < self.ttl:
                return response
            else:
                del self.cache[key]  # Expired
        return None

    def set(self, query: str, response: str, context: str = ""):
        """Cache response"""
        key = self._hash_key(query, context)
        self.cache[key] = (response, datetime.now())

    def _hash_key(self, query: str, context: str) -> str:
        """Generate cache key"""
        combined = f"{query}:{context}"
        return hashlib.md5(combined.encode()).hexdigest()


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

# Affirmative keywords
AFFIRMATIVE_KEYWORDS = {
    "da", "ja", "yes", "seveda", "lahko", "ok", "okay",
    "v redu", "sure", "dobro", "prosim", "please", "grem naprej", "nadaljuj"
}

# Greeting keywords
GREETING_KEYWORDS = {"pozdrav", "zdravo", "hej", "hello", "hi", "dober dan", "živjo"}


def is_affirmative(message: str) -> bool:
    """Check if message is an affirmative response"""
    tokens = message.lower().strip().split()
    if len(tokens) <= 2:  # Short response
        return any(word in AFFIRMATIVE_KEYWORDS for word in tokens)
    return False


def is_negative(message: str) -> bool:
    """Check if message is a negative response"""
    tokens = message.lower().strip().split()
    if len(tokens) <= 3:  # Short response
        return any(word in {"ne", "no", "ne hvala", "preklic", "prekliči", "preklici", "stop", "ne bom"} for word in tokens) or message.lower().strip().startswith("ne ")
    return False


def is_greeting(message: str) -> bool:
    """Check if message is a greeting"""
    lowered = message.lower()
    return any(greet in lowered for greet in GREETING_KEYWORDS)

# ========== ZDRAVSTVENI CENTER INFO ODGOVORI ==========
INFO_RESPONSES = {
    "pozdrav": """Pozdravljeni! 😊

Sem vaš digitalni pomočnik v zdravstvenem centru. Kako vam lahko pomagam?

Lahko vam pomagam z informacijami o naših storitvah, delovnem času, ali pa vas naročim na pregled, če želite.""",

    "kdo_si": """Sem digitalni pomočnik zdravstvenega centra.

Z veseljem odgovorim na vprašanja o naših storitvah, cenah in razpoložljivih terminih.""",

    "ekipa": """Naš zdravstveni center vodi strokovna ekipa zdravnikov in administracije.

Za natančne informacije o vodstvu ali posameznih zdravnikih nas prosim kontaktirajte:
- 📞 01 234 56 78
- 📧 info@zdravstveni-center.si""",

    "hvala": "Hvala za sporočilo! Če boste še kaj potrebovali, sem tukaj za vas. 😊",

    "narocanje": """**Naročanje poteka zelo enostavno - TUKAJ, z menoj!** 🎯

✅ **Kako se naročite:**
1. Poveste mi, kateri pregled vas zanima (dermatolog, ortoped, okulist...)
2. Izberete želeni datum
3. Izberete ustrezen termin
4. Podate svoje podatke (ime, email, telefon)
5. Potrdite naročilo ✅

**To je to!** Celoten postopek traja manj kot 2 minuti.

🚀 **Začnimo ZDAJ** - kateri pregled vas zanima?""",

    "kontakt": """📍 **Naslov**:
Zdravstveni center Ljubljana
Zdraviliška ulica 12
1000 Ljubljana

🕒 **Delovni čas**:
   Pon-Pet: 8:00 - 18:00
   Sobota: 9:00 - 13:00 (samo nujni primeri)

🚗 **Parking**: Brezplačen parking pred objektom
🚌 **Javni prevoz**: Avtobusne linije 6, 11, 20 (postaja "Zdravstveni center")

📞 **Telefon**: 01 234 56 78
📧 **Email**: info@zdravstveni-center.si

💬 **Naročanje terminov**: Lahko se naročite **TUKAJ, z menoj** - samo povejte kateri pregled vas zanima!""",

    "lokacija": """📍 **Zdravstveni center Ljubljana**

**Naslov**:
Zdraviliška ulica 12
1000 Ljubljana

**Kako do nas**:
🚗 Z avtomobilom: Sledite smeri "Center" → Izvoz "Zdravstveni center"
   Brezplačen parking pred objektom za paciente

🚌 Z javnim prevozom:
   - Avtobusne linije: 6, 11, 20
   - Postaja: "Zdravstveni center" (100m od objekta)
   - LPP mestni avtobus

🚶 Peš iz centra: približno 15 minut hoje

📍 Google Maps: Poiščite "Zdravstveni center Ljubljana, Zdraviliška 12"

💬 **Naročite se TUKAJ** - preverim lahko proste termine za vas!""",

    "delovni_cas": """🕒 **Delovni čas**:

**Ponedeljek – Petek**: 8:00 – 18:00
**Sobota**: 9:00 – 13:00 (samo nujni primeri)
**Nedelja in prazniki**: Zaprto

📅 **Termini**:
- Pregledi so na voljo vsak 30 minut
- Priporočamo naročanje vsaj 2 dni vnaprej
- Nujne primere obravnavamo isti dan

💬 **Naročite se ZDAJ** - povejte mi datum in preverim proste termine za vas!

ℹ️ Za druga vprašanja: 01 234 56 78 ali info@zdravstveni-center.si""",

    "storitve": """Najpogostejše storitve:
🔬 dermatolog, 🦴 ortoped, 👁️ okulist,
⚡ laserski posegi, 💉 estetski posegi, 💆 kozmetika.

Napišite, kaj vas zanima, pa povem podrobnosti ali vas naročim.""",

    "dermatolog": """**Dermatološki pregled**
Trajanje: 30 minut
Cena: 25-150 € (odvisno od posega)

Storitve:
- Pregledi kožnih bolezni in sprememb
- Lasersko odstranjevanje žilic in bradavic
- Lasersko zdravljenje glivic nohtov
- Estetski posegi na koži

🎯 **Naročite se ZDAJ** - povejte mi želeni datum!""",

    "ortoped": """**Ortopedski pregled**
Trajanje: 30 minut
Cena: 40-80 €

Storitve:
- Pregledi sklepov in hrbtenice
- Športne poškodbe
- Bolečine v kolenih, ramenih, vratu
- Preventivni ortopedski pregledi

🎯 **Naročite se ZDAJ** - povejte mi želeni datum!""",

    # Symptom-based templates with health advice
    "ortopedija": """Razumem, da imate bolečine. Nekaj nasvetov:

🧊 **Takojšnja pomoč:**
- Počitek in razbremenitev
- Hladen obkladek 15-20 min
- Nežno razgibavanje ko bolečina popusti

**Ortopedski pregled** (30 min, 40-80 €)
- Pregledi sklepov in hrbtenice
- Športne poškodbe
- Bolečine v kolenih, ramenih, hrbtu

⚠️ Če bolečina traja več dni, priporočam pregled.

🎯 **Želite termin?** Povejte mi datum!""",

    "dermatologija": """Razumem vaše skrbi glede kože. Nekaj nasvetov:

🧴 **Splošna nega:**
- Izogibajte se praskanju
- Uporabite blago kremo
- Zaščita pred soncem

**Dermatološki pregled** (30 min, 25-150 €)
- Pregled kožnih sprememb
- Diagnostika kožnih bolezni
- Laserski in estetski posegi

⚠️ Pri sumljivih spremembah priporočam čimprejšnji pregled.

🎯 **Želite termin?** Povejte mi datum!""",

    "oftalmologija": """Razumem, da imate težave z vidom. Nekaj nasvetov:

👁️ **Takojšnja pomoč:**
- Počitek oči (odmor od zaslonov)
- Umetne solze za suhe oči
- Zadostna osvetlitev pri branju

**Okulistični pregled** (30 min, 35-70 €)
- Pregled vida in očesnega ozadja
- Predpis očal in kontaktnih leč
- Merjenje očesnega pritiska

⚠️ Pri nenadnih spremembah vida priporočam čimprejšnji pregled.

🎯 **Želite termin?** Povejte mi datum!""",

    "okulist": """**Okulistični pregled**
Trajanje: 30 minut
Cena: 35-70 €

Storitve:
- Pregled vida in očesnega ozadja
- Predpis očal in kontaktnih leč
- Merjenje očesnega pritiska
- Kontrolni pregledi

🎯 **Naročite se ZDAJ** - povejte mi želeni datum!""",

    "laserski_poseg": """**Laserski posegi**
Trajanje: 30 minut
Cena: 50-200 € (odvisno od posega)

Posegi:
- Odstranjevanje žilic na nogah
- Odstranjevanje bradavic
- Lasersko zdravljenje glivic nohtov

🎯 **Naročite se ZDAJ** - povejte mi želeni datum!""",

    "estetski_poseg": """**Estetski posegi**
Trajanje: 30 minut
Cena: 80-300 € (odvisno od posega)

Posegi:
- Botox proti gubam
- Fillerji za volumen
- Biorevitalizacija kože
- Tretmaji s hialuronsko kislino

🎯 **Naročite se ZDAJ** - povejte mi želeni datum!""",

    "kozmetika": """**Kozmetični salon**
Trajanje: 60 minut
Cena: 40-100 €

Storitve:
- Profesionalna nega obraza
- Globinsko čiščenje kože
- Anti-age tretmaji
- Hidratacija in regeneracija

🎯 **Naročite se ZDAJ** - povejte mi želeni datum!""",

    "cene": """Cena je odvisna od storitve.  
Lahko povem točen razpon, če mi napišete, kateri pregled vas zanima.

Primeri:
• Dermatolog: 25–150 €  
• Ortoped: 40–80 €  
• Okulist: 35–70 €

Kateri pregled vas zanima?""",

    "placilo": """Načini plačila:
- Gotovina
- Kartica (Mastercard, Visa)
- Bančno nakazilo (za podjetja)

Plačilo poteka po opravljenem pregledu/posegu.""",

    "zdravstvena_kartica": """Za preglede prosim prinesite s seboj:
- Veljavno osebno izkaznico
- Zdravstveno kartico (če imate napotnico)
- Dokumentacijo predhodnih pregledov (če obstaja)

Večina naših storitev je samoplačniških, vendar nekatere lahko krijete preko ZZZS napotnice.""",

    "parkiranje": """🚗 **Parkiranje / parking za paciente**:

✅ Brezplačno parkiranje pred zdravstvenim centrom
✅ 50 parkirnih mest
✅ Parkirišče je označeno in dostopno
✅ Prostor za invalide

**Lokacija**: Zdraviliška ulica 12, 1000 Ljubljana

Za navigacijo uporabite Google Maps: "Zdravstveni center Ljubljana".""",

    "prosti_termini": """Za pregled prostih terminov mi prosim povejte:
1. Kateri pregled vas zanima? (dermatolog, ortoped, okulist, ...)
2. Kateri datum? (npr. 15.3.2026)

Preveril bom razpoložljivost.""",
}

# Variante odgovorov
INFO_RESPONSES_VARIANTS = {key: [value] for key, value in INFO_RESPONSES.items()}
INFO_RESPONSES_VARIANTS.update(
    {
        "pozdrav": [
            INFO_RESPONSES["pozdrav"],
            "Pozdravljeni! 😊 Kako vam lahko pomagam danes?",
            "Živjo! Sem digitalni pomočnik zdravstvenega centra. Kako lahko pomagam?",
        ],
        "storitve": [
            INFO_RESPONSES["storitve"],
            "Nudimo dermatologa, ortopeda, okulista ter estetske/laserske posege in kozmetiko. Kaj vas zanima?",
            "Najpogosteje: dermatolog, ortoped, okulist, laser, estetika, kozmetika. Povejte, kaj iščete.",
        ],
        "cene": [
            INFO_RESPONSES["cene"],
            "Cena je odvisna od storitve (npr. 25–150 €). Napišite, kateri pregled vas zanima, pa povem konkreten razpon.",
            "Cena: za točen znesek potrebujem storitev (npr. dermatolog, ortoped, okulist; tipično 25–150 €). Katera vas zanima?",
        ],
        "delovni_cas": [
            INFO_RESPONSES["delovni_cas"],
            "Delovni čas: pon–pet 8:00–18:00, sob 9:00–13:00 (nujni primeri), ned/prazniki zaprto.",
        ],
        "kontakt": [
            INFO_RESPONSES["kontakt"],
            "Naslov: Zdraviliška 12, Ljubljana. Tel: 01 234 56 78. Email: info@zdravstveni-center.si",
        ],
    }
)


def _get_info_response(key: str) -> str:
    variants = INFO_RESPONSES_VARIANTS.get(key) or []
    if variants:
        return random.choice(variants)
    return INFO_RESPONSES.get(key, "Kako vam lahko pomagam?")

# Kritični ključi
BOOKING_RELEVANT_KEYS = {"dermatolog", "ortoped", "okulist", "laserski_poseg", "estetski_poseg", "kozmetika", "storitve", "prosti_termini"}
CRITICAL_INFO_KEYS = {
    "delovni_cas", "kontakt", "cene", "storitve", "prosti_termini",
    "dermatolog", "ortoped", "okulist", "laserski_poseg", "estetski_poseg", "kozmetika"
}

# ===== HYBRID KNOWLEDGE BASE INITIALIZATION =====
# Initialize knowledge base with INFO_RESPONSES using hybrid retrieval (BM25 + OpenAI embeddings)
# This runs once at module import time
_kb_initialized = False

def _ensure_kb_initialized():
    """Lazy initialization of knowledge base to avoid startup delays"""
    global _kb_initialized
    if not _kb_initialized:
        try:
            print("[KB] Initializing hybrid knowledge base with INFO_RESPONSES...")
            kb_module.initialize_knowledge_base(
                documents=INFO_RESPONSES,
                alpha=0.5,  # Equal weight to BM25 and vector search
                use_reranker=True  # Enable cross-encoder re-ranking
            )
            _kb_initialized = True
            print("[KB] Hybrid knowledge base initialized successfully!")
        except Exception as e:
            print(f"[KB] Failed to initialize knowledge base: {e}")
            print("[KB] Will fall back to direct INFO_RESPONSES lookup")

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

INTENT_CLASSIFIER_PROMPT = """Si Intent Classifier za zdravstveni center. Analiziraj SAMO trenutno sporočilo.

STORITVE:
- ortoped: hrbet, koleno, rama, noga, stopalo, roka, gleženj, vrat, sklep
- dermatolog: koža, izpuščaj, akne, mozolj, znamenje, bradavica
- okulist: oči, vid
- kozmetika: obraz, nega obraza
- estetski_poseg: gube, botox, fillerji
- laserski_poseg: žilice, bradavice, glivice

VRNI SAMO JSON (brez markdown):
{"intent": "...", "service": "...", "reason": "..."}

INTENTI:
- "health_advice": uporabnik opisuje simptome/bolečine in potrebuje nasvet
- "booking": uporabnik želi naročiti pregled/termin/naročilo
- "info_narocanje": sprašuje KAJ JE/KAKO POTEKA proces naročanja ("kako se naročim?", "kako poteka naročanje?", "kako rezerviram?")
- "info_services": SAMO splošna vprašanja "kaj nudite" ali "katere storitve imate"
- "info_prices": sprašuje o cenah/ceniku
- "info_contact": sprašuje o lokaciji/kontaktu/naslovu/telefonu
- "info_hours": sprašuje o delovnem času/kdaj ste odprti
- "greeting": pozdrav (zdravo, dober dan, hej)
- "question": SPECIFIČNA vprašanja o storitvah (kdo dela, kakšne izkušnje, kaj vključuje pregled, kakšna je oprema, itd.)

KRITIČNO - RAZLIKUJ MED:
- "info_services" → SAMO "kaj nudite?", "katere storitve imate?", "seznam storitev"
- "info_narocanje" → "kako poteka naročanje?", "kako se naročim?", "kako rezerviram termin?"
- "question" → Specifična vprašanja o storitvah: "kdo dela kot ortoped?", "kaj vključuje pregled?", "kakšna je oprema?", itd.

KRITIČNO - PRAVILA ZA SERVICE:
1. Service vrni SAMO če je storitev EKSPLICITNO omenjena v TRENUTNEM sporočilu
2. Če user reče samo "rad bi se naročil" ali "želim termin" BREZ omembe storitve → service: null
3. NE inferirati storitve iz prejšnjih sporočil ali konteksta!
4. Primeri:
   - "rad bi se naročil na ortopedski pregled" → intent: "booking", service: "ortoped"
   - "rad bi se naročil" → intent: "booking", service: null
   - "kdo dela kot ortoped?" → intent: "question", service: null
   - "kako poteka ortopedski pregled?" → intent: "question", service: null
   - "katere storitve nudite?" → intent: "info_services", service: null
"""

def classify_intent_llm(message: str, history: list = None) -> dict:
    """Use LLM to classify intent - focuses on current message only"""
    from app.core.llm_client import get_llm_client

    prompt = f"""{INTENT_CLASSIFIER_PROMPT}

TRENUTNO SPOROČILO: {message}

JSON:"""

    try:
        client = get_llm_client()
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=[{"role": "user", "content": prompt}],
            max_output_tokens=100,
            temperature=0.1,
        )

        # Extract response text
        answer = getattr(response, "output_text", None)
        if not answer:
            for block in getattr(response, "output", []) or []:
                for content in getattr(block, "content", []) or []:
                    text = getattr(content, "text", None)
                    if text:
                        answer = text
                        break

        # Parse JSON
        if answer:
            # Clean up response
            answer = answer.strip()
            if answer.startswith("```"):
                answer = answer.split("```")[1]
                if answer.startswith("json"):
                    answer = answer[4:]
            result = json.loads(answer)
            return result

    except Exception as e:
        print(f"[INTENT_LLM] Error: {e}")

    # Fallback
    return {"intent": "other", "service": None, "reason": None}


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


def classify_intent(message: str, history: list = None) -> str:
    """Classify intent - FAST rules first, LLM only for complex cases"""

    # Hard guard: booking keywords without explicit service -> book_general (avoid LLM guessing)
    has_price_kw = any(word in message.lower() for word in ["cena", "cene", "cenik", "koliko", "stane"])
    if _has_booking_keywords(message) and not has_price_kw and extract_service_type(message) is None and not any(
        phrase in message.lower()
        for phrase in [
            "kako se naročim", "kako se narocim", "kako poteka naročanje", "kako poteka narocanje",
            "kako rezerviram", "kako rezervirati", "kako do termina", "kako pridem do termina",
        ]
    ):
        return "book_general"

    # FAST PATH: Try rules-based classification first (no API call!)
    rules_intent = classify_intent_rules(message, history)

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


# Old rule-based classify_intent kept as fallback
def classify_intent_rules(message: str, history: list = None) -> str:
    """Rule-based fallback for intent classification"""
    lowered = message.lower()

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
        for service_key, variations in SERVICE_NAME_MAP.items():
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
    for service_key in SERVICES.keys():
        if service_key in lowered or any(var in lowered for var in SERVICE_NAME_MAP.get(service_key, [])):
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


def _service_price_info(service_type: Optional[str]) -> str:
    info = get_service_info(service_type or "")
    if not info:
        return _get_info_response("cene")
    label = service_type or ""
    return f"💰 {label.capitalize()} – {info['name']}: Cena {info['price_range']} · {info['duration_minutes']} min"


def _analyze_query_type(query: str) -> dict:
    """
    Analyze query to determine type and required confidence level

    Returns dict with:
        - type: "booking", "price", "contact", "info", "general"
        - required_confidence: minimum confidence threshold (0-1)
        - priority: "critical", "high", "medium", "low"
    """
    query_lower = query.lower()

    # Booking queries (critical - must be accurate)
    booking_keywords = ["naroč", "termin", "rezerv", "prostem", "prosta", "prosth"]
    if any(kw in query_lower for kw in booking_keywords):
        return {"type": "booking", "required_confidence": 0.7, "priority": "critical"}

    # Price queries (high priority - must be accurate)
    price_keywords = ["cena", "cene", "ceník", "stane", "stroški", "plačil", "koliko"]
    if any(kw in query_lower for kw in price_keywords):
        return {"type": "price", "required_confidence": 0.65, "priority": "high"}

    # Contact/location queries (medium priority)
    contact_keywords = ["naslov", "lokacij", "kako do", "kje", "parking", "telefon", "email", "kontakt"]
    if any(kw in query_lower for kw in contact_keywords):
        return {"type": "contact", "required_confidence": 0.5, "priority": "medium"}

    # Service info queries (medium priority)
    service_keywords = ["dermatolog", "ortoped", "okulist", "lasersk", "estetsk", "kozmetik", "storitev"]
    if any(kw in query_lower for kw in service_keywords):
        return {"type": "info", "required_confidence": 0.55, "priority": "medium"}

    # General queries (lower threshold)
    return {"type": "general", "required_confidence": 0.45, "priority": "low"}


def answer_with_hybrid_kb(query: str, history: list = None, session_id: str = None) -> str:
    """
    Answer question using hybrid knowledge base with enhanced confidence gating

    Uses multi-signal confidence scoring:
    - Search score (hybrid BM25 + vector)
    - Score gap between top results
    - BM25/vector agreement
    - Query type analysis
    - Response validation

    Args:
        query: User question
        history: Conversation history (optional, for future context-aware answers)

    Returns:
        Answer text with confidence-based response strategy
    """
    # Ensure KB is initialized
    _ensure_kb_initialized()

    if not _kb_initialized:
        # Fallback to old method if KB initialization failed
        return generate_llm_answer(query, history=history or [])

    try:
        # ===== QUERY ANALYSIS =====
        query_analysis = _analyze_query_type(query)
        required_confidence = query_analysis["required_confidence"]

        print(f"[CONFIDENCE] Query type: {query_analysis['type']} (priority: {query_analysis['priority']})")
        print(f"[CONFIDENCE] Required confidence threshold: {required_confidence:.2f}")

        # Search knowledge base with hybrid retrieval
        results = kb_module.search_knowledge_base(
            query=query,
            top_k=3,
            min_score=0.0  # Get all results, we'll filter by confidence
        )

        # Store confidence metadata in session state for analytics
        if session_id and results:
            # Ensure state store exists even in legacy deployments
            state_store = globals().setdefault("conversation_state", {})
            state = state_store.get(session_id, {})
            confidence_meta = results[0].get("confidence_metadata", {}) if results else {}
            state["last_confidence_metadata"] = {
                "query_type": query_analysis["type"],
                "query_priority": query_analysis["priority"],
                "required_confidence": required_confidence,
                "overall_confidence": confidence_meta.get("confidence", 0),
                "top_score": confidence_meta.get("top_score", 0),
                "score_gap_ratio": confidence_meta.get("score_gap_ratio", 0),
                "bm25_vector_agreement": confidence_meta.get("bm25_vector_agreement", 0),
                "reranker_used": confidence_meta.get("reranker_used", False),
                "num_results": len(results)
            }
            state_store[session_id] = state

        if not results:
            # No results found - ask for clarification
            return """Nisem prepričan, da pravilno razumem. Lahko pojasnite:
- Za katero storitev vas zanima? (dermatolog / ortoped / okulist / ...)
- Za kateri datum?

Ali lahko zastavite vprašanje drugače?"""

        # Get top result and confidence metadata
        top_result = results[0]
        top_score = top_result["score"]
        confidence_meta = top_result.get("confidence_metadata", {})
        overall_confidence = confidence_meta.get("confidence", top_score)

        # Debug logging
        print(f"[KB_SEARCH] Query: {query[:50]}...")
        print(f"[KB_SEARCH] Top result: {top_result['doc_id']} (score: {top_score:.3f})")
        print(f"[KB_SEARCH] BM25: {top_result['bm25_score']:.3f}, Vector: {top_result['vector_score']:.3f}")

        if confidence_meta:
            print(f"[CONFIDENCE] Overall confidence: {overall_confidence:.3f}")
            print(f"[CONFIDENCE] Score gap ratio: {confidence_meta.get('score_gap_ratio', 0):.3f}")
            print(f"[CONFIDENCE] BM25/Vector agreement: {confidence_meta.get('bm25_vector_agreement', 0):.3f}")
            print(f"[CONFIDENCE] Re-ranker used: {confidence_meta.get('reranker_used', False)}")

        # ===== ENHANCED CONFIDENCE GATING =====

        # Strategy 1: Very high confidence + clear winner
        # Return result directly if confidence is strong and there's clear winner
        score_gap_ratio = confidence_meta.get("score_gap_ratio", 0)
        if overall_confidence >= 0.75 and score_gap_ratio > 0.3:
            print(f"[CONFIDENCE] ✓ Very high confidence + clear winner - returning directly")
            return top_result["text"]

        # Strategy 2: High confidence for query type
        # Return result if it meets the query-specific threshold
        if overall_confidence >= required_confidence:
            # Additional validation for critical queries
            if query_analysis["priority"] == "critical":
                # For critical queries, also check agreement between methods
                agreement = confidence_meta.get("bm25_vector_agreement", 0)
                if agreement < 0.5:
                    print(f"[CONFIDENCE] ⚠ Critical query but low method agreement - using LLM")
                    # Fall through to LLM strategy
                else:
                    print(f"[CONFIDENCE] ✓ High confidence for critical query - returning directly")
                    return top_result["text"]
            else:
                print(f"[CONFIDENCE] ✓ Meets query-type threshold - returning directly")
                return top_result["text"]

        # Strategy 3: Medium confidence - Use LLM with context
        # If confidence is moderate, use LLM to synthesize answer from retrieved docs
        if overall_confidence >= 0.35:
            print(f"[CONFIDENCE] ~ Medium confidence - using LLM with retrieved context")

            # Gather context from top 2-3 results depending on confidence
            num_context_docs = 2 if overall_confidence >= 0.45 else 3
            context_docs = [r["text"] for r in results[:num_context_docs]]
            context = "\n\n---\n\n".join(context_docs)

            # Generate answer using LLM with context
            llm_client = get_llm_client()

            system_prompt = """Si digitalni pomočnik zdravstvenega centra.
Odgovarjaj na podlagi danega konteksta. Če kontekst ne vsebuje informacij za odgovor, reci to prijazno.
Odgovori naj bodo kratki in jedrnati."""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"""Kontekst:
{context}

Vprašanje: {query}

Odgovori na slovenščini na podlagi konteksta zgoraj."""}
            ]

            response = llm_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.3,
                max_tokens=300
            )
            answer = response.choices[0].message.content.strip()

            # Validate LLM response quality
            if len(answer) < 20:
                print(f"[CONFIDENCE] ⚠ LLM response too short - returning top result instead")
                return top_result["text"]

            # Check if LLM declined to answer (common phrases)
            decline_phrases = ["ne vem", "nimam informacij", "ne najdem", "ne morem", "žal ne"]
            if any(phrase in answer.lower() for phrase in decline_phrases):
                print(f"[CONFIDENCE] ⚠ LLM declined - returning top result instead")
                return top_result["text"]

            return answer

        # Strategy 4: Low confidence - Ask for clarification
        # If confidence is too low, ask user to clarify their question
        print(f"[CONFIDENCE] ✗ Low confidence ({overall_confidence:.3f}) - asking for clarification")

        # Provide contextual clarification based on query type
        if query_analysis["type"] == "booking":
            return """Za naročanje potrebujem naslednje podatke:
- Kateri pregled vas zanima? (dermatolog, ortoped, okulist, laserski poseg, estetski poseg, kozmetika)
- Kateri datum vas zanima?

Prosim, navedite obe informaciji."""

        elif query_analysis["type"] == "price":
            return """Za točne cene mi prosim povejte katera storitev vas zanima:

🔬 Dermatologija
🦴 Ortopedija
👁️ Oftalmologija
⚡ Laserski posegi
💉 Estetski posegi
💆 Kozmetični salon

Katero storitev želite?"""

        else:
            # General clarification
            return """Lahko vam pomagam z:
- Naročilom na pregled (dermatolog, ortoped, okulist...)
- Informacijami o storitvah in cenah
- Delovnim časom in lokacijo
- Prostimi termini

Kaj vas zanima?"""

    except Exception as e:
        print(f"[KB_SEARCH] Error: {e}")
        import traceback
        traceback.print_exc()

        # Fallback to old method
        return generate_llm_answer(query, history=history or [])


def generate_health_advice(symptom_description: str) -> str:
    """
    Generate personalized health advice using LLM.
    Gives general wellness tips (NOT diagnosis) and suggests appropriate specialist.
    """
    try:
        llm_client = get_llm_client()

        system_prompt = """Si zdravstveni svetovalec. Daj SPLOŠNE nasvete (počitek, obkladki, razgibavanje) - NIKOLI diagnoz.

Format: 1 kratek odstavek + 2 kratki alineji + priporočilo specialista.
Največ 90 besed.
Ne uporabljaj oštevilčenja (1/2/3).
Zaključi z: "Želite, da vas naročim na pregled?"

Slovenščina, jedrnato."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": symptom_description}
        ]

        # Use correct OpenAI API - gpt-4o-mini is fast
        response = llm_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.3,
            max_tokens=170
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"[HEALTH_ADVICE] Error: {e}")
        # Fallback to generic response
        return """Razumem, da imate zdravstvene težave in da je to lahko zelo neprijetno.

Nekaj splošnih nasvetov:
- Počitek in razbremenitev prizadetega dela
- Zadostna hidracija
- Nežno razgibavanje, če bolečina dopušča

Če težave trajajo več dni ali se stopnjujejo, priporočam pregled pri specialistu (ortoped/dermatolog/okulist, odvisno od težav).

Želite, da vas naročim na pregled?"""


def _service_booking_label(service_key: Optional[str]) -> Optional[str]:
    if not service_key:
        return None
    labels = {
        "ORTOPED": "ortopedski pregled",
        "DERMATOLOG": "dermatološki pregled",
        "OKULIST": "okulistični pregled",
        "LASERSKI_POSEG": "laserski poseg",
        "ESTETSKI_POSEG": "estetski poseg",
        "FIZIOTERAPIJA": "fizioterapija",
        "KOZMETIKA": "kozmetični pregled",
    }
    return labels.get(service_key)


def answer_health_query(message: str, preferred_service: Optional[str] = None) -> str:
    """
    Health advice strategy:
    - Always provide safe LLM advice + offer booking.
    """
    try:
        advice = generate_health_advice(message)
        label = _service_booking_label(preferred_service)
        if label:
            return f"Glede na opis bi bil najbolj smiseln **{label}**.\n\n{advice}"
        return advice
    except Exception as e:
        print(f"[HEALTH_ADVICE] Fallback error: {e}")
        return generate_health_advice(message)


def extract_service_type(message: str) -> Optional[str]:
    """Extract service type from message using word boundary matching"""
    import re
    lowered = message.lower()

    # Skip short keywords that cause false positives
    skip_keywords = {"oči", "oci"}  # "oči" matches "naročil"

    for service_key, variations in SERVICE_NAME_MAP.items():
        for var in variations:
            # Skip problematic short keywords
            if var in skip_keywords:
                continue
            # Use word boundary to avoid substring matches
            if re.search(r'\b' + re.escape(var), lowered):
                return service_key

    return None

def detect_service_from_message(message: str) -> Optional[str]:
    """Backward-compatible alias for older call sites."""
    return extract_service_type(message)

BOOKING_FLOW_DEPS = BookingFlowDeps(
    get_appointment_state=get_appointment_state,
    reset_appointment_state=reset_appointment_state,
    reset_unified_state=reset_unified_state,
    reset_loop_count=conversation_tracker.reset_loop_count,
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


def get_resume_prompt(state: dict) -> str:
    """Backward-compatible wrapper around extracted booking flow."""
    return booking_get_resume_prompt(state, BOOKING_FLOW_DEPS)


def handle_appointment_booking(message: str, session_id: str) -> str:
    """Backward-compatible wrapper around extracted booking flow."""
    return booking_handle_appointment_booking(message, session_id, BOOKING_FLOW_DEPS)


# ============================================================
# UNIFIED ROUTING SYSTEM - New architecture
# ============================================================

def handle_unified_routing(message: str, session_id: str) -> str | None:
    """
    Handle message using unified routing system.
    Returns response string, or None if should fall back to legacy system.
    """
    appointment_state = get_appointment_state(session_id)
    unified_state = get_unified_state(session_id)
    context = unified_state.setdefault("context", {})

    def _clear_booking_details_preserve_service() -> None:
        """Clear appointment details when changing service, keep only service type."""
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
            appointment_state["service_type"] = pending_service_key
            _clear_booking_details_preserve_service()
            context["pending_service_switch"] = None

            if pending_info:
                return (
                    f"Super, preklopim na **{pending_info['name']}**.\n\n"
                    f"📋 Trajanje: {pending_info['duration_minutes']} minut\n"
                    f"💰 Cena: {pending_info['price_range']}\n\n"
                    "Kateri datum vas zanima? (npr. 15.3.2026)"
                )
            return "Super, preklopim storitev. Kateri datum vas zanima? (npr. 15.3.2026)"

        if is_negative(message):
            context["pending_service_switch"] = None
            step = appointment_state.get("step") or get_current_step(session_id)
            return build_resume_prompt(step) or "V redu, nadaljujemo z naročilom."

    # Keep unified state in sync with legacy appointment state.
    if appointment_state.get("step"):
        unified_state["flow"] = FlowType.APPOINTMENT.value
        unified_state["step"] = appointment_state.get("step")
    else:
        unified_state["flow"] = FlowType.IDLE.value
        unified_state["step"] = None

    decision = unified_route(message, unified_state)
    suggested_service = context.get("suggested_service")

    # If user provides a date after service info prompt, start booking immediately
    date_str = extract_date_from_message(message)
    if date_str and suggested_service and not is_in_flow(session_id):
        appointment_state["service_type"] = suggested_service.lower()
        appointment_state["step"] = None
        start_flow(session_id, FlowType.APPOINTMENT, FlowStep.DATE)
        context["suggested_service"] = None
        return handle_appointment_booking(message, session_id)

    # Log decision for debugging
    print(f"[UNIFIED] Intent: {decision.primary_intent.value}, Confidence: {decision.confidence:.2f}, Action: {decision.action.value}, Service: {decision.service_type}")

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
        appointment_state["service_type"] = suggested_service.lower()
        appointment_state["step"] = None
        start_flow(session_id, FlowType.APPOINTMENT, FlowStep.DATE)
        context["suggested_service"] = None
        return handle_appointment_booking(message, session_id)

    if decision.primary_intent == IntentType.NEGATIVE and is_in_flow(session_id):
        reset_unified_state(session_id)
        return "V redu, naročilo preklicano. Kako vam lahko drugače pomagam?"

    # Handle GREETING
    if decision.primary_intent == IntentType.GREETING:
        return _get_info_response("pozdrav")

    # Handle GOODBYE
    if decision.primary_intent == IntentType.GOODBYE:
        return _get_info_response("hvala")

    # Handle SOFT_INTERRUPT during booking flow
    if decision.action == SwitchAction.SOFT_INTERRUPT and is_in_flow(session_id):
        step = appointment_state.get("step") or get_current_step(session_id)

        # If flow expects date but service is missing, use detected service first.
        if step == "date" and not appointment_state.get("service_type") and decision.service_type:
            appointment_state["service_type"] = decision.service_type.lower()
            return handle_appointment_booking(message, session_id)

        # If user is answering the expected booking step, do not interrupt.
        if step == "date" and extract_date_from_message(message):
            return None
        if step == "time" and extract_time_from_message(message):
            return None
        if step == "select_service" and extract_service_type(message):
            return None
        if step == "name" and is_likely_full_name(message):
            return None
        if step == "phone":
            phone_candidate = re.sub(r"[^\d+]", "", message)
            if len(phone_candidate) >= 8:
                return None
        if step == "email" and ("@" in message and "." in message.split("@")[-1]):
            return None
        if step == "reason" and message.strip():
            return None

        # Answer the interrupting question
        service_hint = decision.service_type or appointment_state.get("service_type") or suggested_service
        if decision.primary_intent == IntentType.SERVICE_INFO and service_hint:
            service_info = get_service_info(str(service_hint).lower())
            if service_info:
                current_service = appointment_state.get("service_type")
                incoming_service = str(service_hint).lower()
                if current_service and incoming_service != current_service:
                    current_info = get_service_info(current_service)
                    current_label = current_info["name"] if current_info else current_service
                    context["pending_service_switch"] = incoming_service
                    return (
                        f"Glede na opis priporočam **{service_info['name']}** "
                        f"({service_info['duration_minutes']} min, {service_info['price_range']}).\n\n"
                        f"Trenutno imate izbran **{current_label}**.\n"
                        f"Želite preklopiti na **{service_info['name']}**? (DA / NE)"
                    )

        answer = resolve_interrupt_answer(
            message=message,
            primary_intent=decision.primary_intent,
            service_hint=decision.service_type or suggested_service,
            active_service=appointment_state.get("service_type"),
            deps=INTERRUPT_FLOW_DEPS,
        )

        if answer:
            return build_interrupt_response(answer, step, include_resume=True)

    # Handle BOOKING_APPOINTMENT intent
    if decision.primary_intent == IntentType.BOOKING_APPOINTMENT:
        if not is_in_flow(session_id):
            # Start new booking flow
            service_type = decision.service_type
            if service_type:
                set_appointment_field(session_id, "service_type", service_type)
                appointment_state["service_type"] = service_type.lower()
                appointment_state["step"] = None
                start_flow(session_id, FlowType.APPOINTMENT, FlowStep.DATE)
                return f"Odlično! Naročilo za {service_type.lower()}. Kateri datum vam ustreza? (npr. 15.2.2026)"
            else:
                start_flow(session_id, FlowType.APPOINTMENT, FlowStep.SERVICE)
                appointment_state["service_type"] = None
                appointment_state["step"] = "select_service"
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
        service = decision.service_type
        if service:
            unified_state.setdefault("context", {})["suggested_service"] = service
            appointment_state["service_type"] = service.lower()
            appointment_state["step"] = None
            if _looks_like_symptom_report(message):
                service_info = get_service_info(service.lower())
                if service_info:
                    return (
                        f"Razumem. Za zdaj svetujem počitek in brez večjih obremenitev.\n\n"
                        f"Glede na opis priporočam **{service_info['name']}** "
                        f"({service_info['duration_minutes']} min, {service_info['price_range']}).\n\n"
                        "🎯 Želite termin? Povejte mi datum!"
                    )
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
            return _get_info_response("storitve")

    # Handle PRICE
    if decision.primary_intent == IntentType.PRICE:
        service = decision.service_type or suggested_service or appointment_state.get("service_type")
        if service:
            service_key = service.lower()
            return _service_price_info(service_key)
        return _get_info_response("cene")

    # Handle INFO
    if decision.primary_intent == IntentType.INFO:
        lowered = message.lower()
        info_key = pick_info_key(message)
        if info_key != "kontakt":
            return _get_info_response(info_key)
        if any(k in lowered for k in ["pridem", "pridemo", "pot"]):
            return INFO_RESPONSES.get("lokacija")
        return _get_info_response("kontakt")

    # For other intents, fall back to legacy system
    return None


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Main chat endpoint (D4): unified router only, legacy path removed."""
    global conversation_history, last_interaction, chat_session_id

    message = request.message.strip()
    session_id = request.session_id or chat_session_id

    if not message:
        payload = format_response(
            "Prosim napišite sporočilo, da vam lahko pomagam.",
            metadata={"contract_version": "v0.1", "router": "unified_only"},
        )
        return ChatResponse(reply=payload["text"], session_id=session_id, metadata=payload["metadata"])

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
                metadata={"contract_version": "v0.1", "router": "unified_only", "loop_guard": True},
            )
            return ChatResponse(reply=payload["text"], session_id=session_id, metadata=payload["metadata"])
        payload = format_response(
            "Opazil sem ponavljanje. Prosim povejte konkretno: pregled + datum.",
            metadata={"contract_version": "v0.1", "router": "unified_only", "loop_guard": True},
        )
        return ChatResponse(reply=payload["text"], session_id=session_id, metadata=payload["metadata"])

    conversation_tracker.add_message(session_id, message)

    # Primary path: unified routing handler
    response_text = handle_unified_routing(message, session_id)

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

    try:
        flow_state = get_unified_state(session_id)
        appointment_state = get_appointment_state(session_id)
        current_step = appointment_state.get("step") if appointment_state.get("step") is not None else None
        metadata["flow"] = flow_state.get("flow")
        metadata["booking_step"] = current_step

        ui_payload = _build_ui_payload(appointment_state, response_text)
        if ui_payload:
            metadata["ui"] = ui_payload
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

    payload = format_response(response_text, metadata=metadata)
    return ChatResponse(reply=payload["text"], session_id=session_id, metadata=payload["metadata"])


def _build_ui_payload(appointment_state: dict[str, Any], response_text: str | None) -> Optional[dict[str, Any]]:
    step = appointment_state.get("step")
    response_text = response_text or ""

    if step in (None, "select_service") and "Na kateri pregled" in response_text:
        return {
            "type": "service_select",
            "label": "Izberite storitev",
            "options": [
                {"label": "Dermatološki pregled", "value": "Dermatološki pregled"},
                {"label": "Ortopedski pregled", "value": "Ortopedski pregled"},
                {"label": "Okulistični pregled", "value": "Okulistični pregled"},
                {"label": "Laserski poseg", "value": "Laserski poseg"},
                {"label": "Estetski poseg", "value": "Estetski poseg"},
                {"label": "Kozmetični salon", "value": "Kozmetični salon"},
            ],
        }

    if step == "date":
        return {
            "type": "date_picker",
            "label": "Izberite datum",
            "min_date": date.today().isoformat(),
        }

    if step == "time":
        date_str = str(appointment_state.get("date") or "")
        service_type = str(appointment_state.get("service_type") or "")
        slots: list[str] = []
        if date_str and service_type:
            try:
                slots = get_available_time_slots(date_str, service_type)
            except Exception:
                slots = []
        if slots:
            return {
                "type": "time_slots",
                "label": f"Prosti termini za {date_str}",
                "slots": slots[:12],
            }

    if step == "confirm" or "Ali so podatki pravilni" in response_text:
        return {
            "type": "confirm",
            "label": "Ali so podatki pravilni?",
            "options": ["DA", "NE"],
        }

    return None


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
    session_id: str = None
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
            session_id=session_id
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
