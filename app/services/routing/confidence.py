"""
Confidence scoring for health center intent detection.
3-level system: HARD_SWITCH (>0.8), SOFT_INTERRUPT (0.5-0.8), IGNORE (<0.5)
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, Tuple
import re

from app.services.routing.symptom_lexicon import (
    DERMATOLOGY_HINTS,
    OPHTHALMOLOGY_HINTS,
    ORTHOPEDICS_HINTS,
)


class SwitchAction(str, Enum):
    HARD_SWITCH = "hard_switch"
    SOFT_INTERRUPT = "soft_interrupt"
    IGNORE = "ignore"


def decide_action(confidence: float) -> SwitchAction:
    if confidence >= 0.8:
        return SwitchAction.HARD_SWITCH
    if confidence >= 0.5:
        return SwitchAction.SOFT_INTERRUPT
    return SwitchAction.IGNORE


# ============ APPOINTMENT BOOKING KEYWORDS ============

APPOINTMENT_KEYWORDS = {
    "termin",
    "naročiti",
    "narociti",
    "naročim",
    "narocim",
    "naročil",
    "narocil",
    "naročilo",
    "narocilo",
    "rezerv",
    "pregled",
    "poseg",
    "posege",
    "tretma",
    "tretmaji",
    "kontrola",
    "kontrolo",
    "obisk",
    "priti",
    "pridem",
}

BOOKING_HINTS = {
    "rad bi",
    "rada bi",
    "bi rad",
    "bi rada",
    "želim",
    "zelim",
    "rabim",
    "potrebujem",
    "lahko naročim",
    "lahko narocim",
    "se naročim",
    "se narocim",
    "lohk",        # sleng
    "bi lohk",     # sleng
    "mam lohk",    # sleng
    "a lohk",      # sleng
    "dobim",       # "a lahko dobim"
    "book",        # english
    "booking",     # english
    "appointment", # english
    "need",        # english
    "want",        # english
    "slots",       # english: "free slots"
}

# ============ SERVICE TYPE KEYWORDS ============

DERMATOLOGY_KEYWORDS = {
    "dermatolog",
    "dermato",
    "dermatalog",
    "dermatalogu",
    "dermatlog",  # typo
    "koža",
    "koza",
    "kozo",      # sleng/typo: "s kozo"
    "kožo",      # "s kožo"
    "koži",
    "kozi",
    "kožn",
    "kozn",
    "akne",
    "luskavica",
    "psoriaza",
    "izpuščaj",
    "izpuscaj",
    "težave s kož",  # težave s kožo
    "tezave s koz",  # typo: težave s kožo
    "madež",
    "madez",
    "melanom",
    "znamenje",
    "znamnje",   # typo
    "skin",
    "rash",
    "mole",
    "acne",
    "glivic",
}
DERMATOLOGY_KEYWORDS |= DERMATOLOGY_HINTS

ORTHOPEDICS_KEYWORDS = {
    "ortoped",
    "ortopet",  # typo
    "ortopd",   # typo
    "hrbet",
    "hrbten",
    "kolen",
    "hrbtom",
    "koleno",
    "nogo",
    "noga",
    "gleženj",
    "glezenj",
    "stopalo",
    "rama",
    "ramo",
    "sklep",
    "mišic",
    "misic",
    "bolečin",
    "bolecin",
    "poškodb",
    "poskodb",
    "športn",
    "sportn",
    "zlom",
    "back",     # english
    "hurts",    # english
    "knee",
    "knees",
    "shoulder",
    "joint",
    "zapestje",
    "zapestja",
    "zapestju",
    "wrist",
}
ORTHOPEDICS_KEYWORDS |= ORTHOPEDICS_HINTS

# Keywords that need word boundary matching
ORTHOPEDICS_WORDS = {
    "kolka",
    "kolku",
}

OPHTHALMOLOGY_KEYWORDS = {
    "okulist",
    "okulsit",  # typo
    "okulist",
    "oftalmolog",
    "ocena vida",
    "očal",
    "ocal",
    "leče",
    "lece",
    "očesn",
    "ocesn",
    "vidim",
    "slabo vid",
    "slabše vid",
    "ocmi",     # typo za oči
    "oceh",     # typo
    "eye",
    "eyes",
    "vision",
    "eye check",
    "eye exam",
}
OPHTHALMOLOGY_KEYWORDS |= OPHTHALMOLOGY_HINTS

# Keywords that need word boundary matching (to avoid "oci" in "naročilo")
OPHTHALMOLOGY_WORDS = {
    "oči",
    "oci",
    "vid",
    "eye",
    "eyes",
}

AESTHETIC_KEYWORDS = {
    "botox",
    "botoks",
    "botoc",
    "filler",
    "filer",
    "fillerji",
    "fillerj",
    "estetsk",
    "biorevital",
    "pomlajev",
    "gube",
    "gubic",
}

LASER_KEYWORDS = {
    "laser",
    "lasersk",
    "žilic",
    "zilic",
    "kapilare",
    "bradavic",
    "bradavica",
    "bradavice",
    "glivic",
}

PHYSIOTHERAPY_KEYWORDS = {
    "fizioterapevt",
    "fizioterapij",
    "fizikalna",
    "rehabilit",
    "masaž",
    "masaz",
    "masaže",
    "masaze",
    "masaža",
    "masaza",
    "masaše",
    "masase",
    "razgib",
    "vaje",
}

COSMETICS_KEYWORDS = {
    "kozmetik",
    "kozmetičn",
    "kozmeticn",
    "nega",
    "obraz",
    "tretma",
    "masaža",
    "masaza",
    "masaže",
    "masaze",
    "masaše",
    "masase",
}

# All service keywords combined
SERVICE_KEYWORDS = (
    DERMATOLOGY_KEYWORDS
    | ORTHOPEDICS_KEYWORDS
    | OPHTHALMOLOGY_KEYWORDS
    | AESTHETIC_KEYWORDS
    | LASER_KEYWORDS
    | PHYSIOTHERAPY_KEYWORDS
    | COSMETICS_KEYWORDS
)

# General service inquiry keywords (for SERVICE_INFO intent)
SERVICE_INQUIRY_KEYWORDS = {
    "bolezni",
    "zdravite",
    "zdravijo",
    "delate",
    "ponujate",
    "storitve",
    "kakšne",
    "katere",
    "a delate",
    "a zdravite",
    "kaj pomaga",
    "kako poteka",
    "kaj vključuje",
    "kaj vkljucuje",  # brez šumnikov
    "kaj vsebuje",
    "bi rad vedel",   # info request
    "bi rada vedela", # info request
    "informacije",
    "informacij",
    "zanima me",
    "me zanima",
    "prpelat",        # sleng: kaj moram pripeljat
    "prinest",        # kaj moram prinest
    "kdo dela",
    "kdo je",
    "vprašanje",
    "vprasanje",
    "vprasat",        # sleng
    "izvid",
    "izvide",
    "izvidi",
    "napotnic",
    "napotnico",
    "napotnica",
    "kaj rabim",
    "kaj potrebujem",
    "prinesem",
    "moram prinesti",
    "pred pregledom",
}

# Pre-visit preparation questions should be treated as info intent,
# not as direct booking intent.
PREVISIT_INFO_KEYWORDS = {
    "izvid",
    "izvide",
    "izvidi",
    "napotnic",
    "napotnico",
    "napotnica",
    "napotnco",
    "rtg",
    "mr",
    "magnetna",
    "pred pregledom",
    "s sabo",
    "moram prinesti",
    "prinesem",
}

# Symptom keywords to trigger SERVICE_INFO (health advice path)
SYMPTOM_KEYWORDS = {
    "boli",
    "boleč",
    "bolec",
    "bolečin",
    "bolecin",
    "glava",
    "glavobol",
    "migrena",
    "srbi",
    "srbec",
    "srbeč",
    "srbe",
    "izpuščaj",
    "izpuscaj",
    "bula",
    "bulo",
    "bulica",
    "otekl",
    "otekla",
    "oteklo",
    "slabo vidim",
    "vidim slabše",
    "slabse vidim",
    "poškod",
    "poskod",
    "poškodoval",
    "poskodoval",
    "zapestje",
}
# ============ INFO KEYWORDS ============

INFO_KEYWORDS = {
    "kdaj",
    "kdja",      # typo
    "kje",
    "kam",
    "kko",       # sleng: kako
    "odprto",
    "odprti",
    "delovni čas",
    "delovni cas",
    "delovn",
    "delovn cas",
    "kaksn delovn",
    "kaksen delovn",
    "ura",
    "urnik",
    "naslov",
    "lokacija",
    "parking",
    "parkirni",
    "parkirni prostor",
    "parkplac",  # sleng
    "parkirišče",
    "parkirisce",
    "kontakt",
    "telefon",
    "email",
    "e-mail",
    "kako pridem",
    "kako pridm", # sleng
    "kako pridemo",
    "kako se naročim",
    "kako se narocim",
    "naročanje",
    "narocanje",
    "kje ste",
    "kje se nahajate",
    "kje se nhajaet",  # typo
    "mate",      # sleng za "imate"
    "located",   # english
    "where",     # english
}

PRICE_KEYWORDS = {
    "cena",
    "cenik",
    "koliko stane",
    "koliko je",
    "koliko stan",
    "kolko stane", # sleng
    "kolko je",
    "kolko",       # sleng
    "koliko pride",
    "kolko pride",
    "kva stane",   # sleng
    "cene",
    "stroški",
    "stroski",
    "plačilo",
    "placilo",
    "račun",
    "racun",
    "zavarovanje",
    "zzzs",
    "dopolnilno",
    "drago",       # sleng: "a je drago"
    "price",       # english
    "prices",      # english
    "cost",        # english
    "how much",    # english
}

# ============ GREETING/GOODBYE ============

GREETING_KEYWORDS = {
    "zdravo",
    "zdravjo",   # typo
    "živjo",
    "zivjo",
    "dobro jutro",
    "dober dan",
    "hello",
    "hej",
    "pozdravljeni",
}

# Keywords that need word boundary matching (to avoid "ej" in "okej")
GREETING_WORDS = {
    "ej",   # needs boundary to not match "okej"
    "hi",   # needs boundary to not match inside words
}

GOODBYE_KEYWORDS = {
    "hvala",
    "hvaal",     # typo
    "hval",      # typo
    "thanks",    # english
    "adijo",
    "nasvidenje",
    "lep pozdrav",
    "lp",
    "bye",
    "čao",
    "cao",
    "ciao",
    "se vidimo",
    "na svidenje",
}
# Note: "pozdrav" removed - conflicts with "pozdravljeni" (greeting)

# ============ URGENCY KEYWORDS ============

URGENCY_KEYWORDS = {
    "nujno",
    "takoj",
    "danes",
    "čimprej",
    "cimprej",
    "urgentno",
    "hudo",
    "zelo boli",
    "močno boli",
    "mocno boli",
    "težko diham",
    "tezko diham",
    "duši",
    "dusi",
    "bolečina v prs",
    "bolecina v prs",
    "prsih",
    "krvavim",
    "krvavi",
}

QUESTION_MARKERS = {"?", "ali", "a ", "a imate", "imate", "kaj", "koliko", "kdaj", "kje"}
FOOD_CONTEXT_KEYWORDS = {"kosilo", "jedel", "jest", "hrana", "meni", "jedilnik"}


def _ascii_fold(text: str) -> str:
    return (
        text.replace("š", "s")
        .replace("č", "c")
        .replace("ž", "z")
        .replace("đ", "d")
    )


def _build_service_keywords(service_map: Dict[str, list[str]] | None) -> set[str]:
    keywords: set[str] = set(SERVICE_KEYWORDS)
    if not service_map:
        return keywords
    for values in service_map.values():
        for kw in values:
            if isinstance(kw, str) and kw:
                token = kw.lower()
                keywords.add(token)
                folded = _ascii_fold(token)
                if folded and folded != token:
                    keywords.add(folded)
    return keywords


def _score_from_keywords(message: str, keywords: set[str]) -> float:
    return 0.4 if any(k in message for k in keywords) else 0.0


def _score_question_marker(message: str) -> float:
    return 0.3 if any(m in message for m in QUESTION_MARKERS) else 0.0


def _contains_word(message: str, words: set[str]) -> bool:
    """Word-boundary match to avoid false positives."""
    return any(re.search(rf"\b{re.escape(w)}\b", message, re.IGNORECASE) for w in words)


def _detect_service_type(text: str, service_map: Dict[str, list[str]] | None = None) -> str | None:
    """Detect specific service type from message."""
    if service_map:
        matches: dict[str, int] = {}
        folded_text = _ascii_fold(text)
        for service_key, keywords in service_map.items():
            if not isinstance(keywords, list):
                continue
            count = 0
            for kw in keywords:
                if not isinstance(kw, str):
                    continue
                token = kw.lower()
                token_folded = _ascii_fold(token)
                if len(token) <= 3:
                    if _contains_word(text, {token}) or _contains_word(folded_text, {token_folded}):
                        count += 1
                elif token in text or token_folded in folded_text:
                    count += 1
            if count:
                matches[service_key] = count
        if matches:
            # Prefer laser if any laser-specific keyword appears
            if "laserski_poseg" in matches and any(k in text for k in {"laser", "lasersk"}):
                return "LASERSKI_POSEG"
            best = max(matches.items(), key=lambda item: item[1])[0]
            return best.upper()

    # Order matters - more specific first, then check word-boundary matches
    # Explicit laser mention should win over generic skin keywords (e.g. "laserski poseg za bradavice")
    if any(k in text for k in {"laser", "lasersk"}):
        return "LASERSKI_POSEG"
    if any(k in text for k in DERMATOLOGY_KEYWORDS):
        return "DERMATOLOG"
    if any(k in text for k in ORTHOPEDICS_KEYWORDS):
        return "ORTOPED"
    # Also check word-boundary matches for "kolk" (hip) to avoid matching "kolko" (how much)
    if _contains_word(text, ORTHOPEDICS_WORDS):
        return "ORTOPED"
    # Check LASER and PHYSIOTHERAPY before OPHTHALMOLOGY (more specific)
    if any(k in text for k in LASER_KEYWORDS):
        return "LASERSKI_POSEG"
    if any(k in text for k in PHYSIOTHERAPY_KEYWORDS):
        return "FIZIOTERAPIJA"
    if any(k in text for k in AESTHETIC_KEYWORDS):
        return "ESTETSKI_POSEG"
    if any(k in text for k in COSMETICS_KEYWORDS):
        return "KOZMETIKA"
    # OPHTHALMOLOGY last - check both substring and word-boundary
    if any(k in text for k in OPHTHALMOLOGY_KEYWORDS):
        return "OKULIST"
    if _contains_word(text, OPHTHALMOLOGY_WORDS):
        return "OKULIST"
    return None


def compute_confidence(
    message: str,
    intent: str,
    service_keywords: set[str] | None = None,
) -> float:
    """Compute confidence score for given intent."""
    text = message.lower()
    service_keywords = service_keywords or SERVICE_KEYWORDS

    # Pre-compute common signals
    has_appointment_kw = any(k in text for k in APPOINTMENT_KEYWORDS)
    has_service_kw = any(k in text for k in service_keywords)
    has_booking_hint = any(k in text for k in BOOKING_HINTS)
    has_greeting_kw = any(k in text for k in GREETING_KEYWORDS) or _contains_word(text, GREETING_WORDS)
    has_price_kw = any(k in text for k in PRICE_KEYWORDS)
    has_inquiry_kw = any(k in text for k in SERVICE_INQUIRY_KEYWORDS)
    has_info_kw = any(k in text for k in INFO_KEYWORDS)

    # Special check: "kako pridem" is INFO, not booking
    is_kako_pridem = "kako pridem" in text or "kako pridemo" in text
    # Special check: "kako se naročim" is INFO, not booking
    is_kako_narocim = "kako se naročim" in text or "kako se narocim" in text

    if intent == "GREETING":
        if not has_greeting_kw:
            return 0.0
        # If message has booking/appointment intent, downgrade greeting
        if has_appointment_kw or has_booking_hint:
            return 0.3  # Let BOOKING win
        # If message has price/info intent, downgrade greeting
        if has_price_kw or has_info_kw:
            return 0.3
        # If message has service keywords (symptoms), downgrade greeting
        if has_service_kw:
            return 0.3  # Let SERVICE_INFO win
        # Pure greeting
        return 1.0

    if intent == "GOODBYE":
        return 1.0 if any(k in text for k in GOODBYE_KEYWORDS) else 0.0

    if intent == "BOOKING_APPOINTMENT":
        if any(k in text for k in URGENCY_KEYWORDS):
            return 0.1

        # "Kako pridem" is INFO, not booking
        if is_kako_pridem:
            return 0.0
        # "Kako se naročim" is INFO, not booking
        if is_kako_narocim:
            return 0.0

        # If asking about price, this is PRICE not booking
        if has_price_kw and not has_booking_hint:
            return 0.3

        # If inquiry keywords present, this is likely SERVICE_INFO not booking
        if has_inquiry_kw and not has_booking_hint:
            return 0.3  # Lower than SERVICE_INFO's 0.9

        # "Ali potrebujem izvide pred pregledom kolena?" and similar:
        # user asks preparation question, not immediate booking.
        has_previsit_kw = any(k in text for k in PREVISIT_INFO_KEYWORDS)
        has_question = _score_question_marker(text) > 0
        if has_previsit_kw and has_question:
            return 0.2

        # Strong signal: explicit appointment + service type
        if has_appointment_kw and has_service_kw:
            if not has_booking_hint and not any(k in text for k in {"naroč", "naroc", "rezerv", "termin"}):
                return 0.4
            return 0.95

        # Strong signal: booking hint + service type
        if has_booking_hint and has_service_kw:
            # If no explicit appointment keyword, favor SERVICE_INFO over booking
            if not has_appointment_kw:
                if any(k in text for k in {"rabim", "potrebujem", "hočem", "hocem", "rad bi", "rada bi", "bi rad", "bi rada", "appointment", "book", "booking", "need", "want"}):
                    return 0.85
                return 0.45
            return 0.9

        # Strong signal: booking hint + appointment keyword
        if has_booking_hint and has_appointment_kw:
            return 0.85

        # Medium signal: just appointment keyword (not "pridem" alone)
        if has_appointment_kw:
            base = 0.6
            if has_booking_hint:
                base += 0.2
            base += _score_question_marker(text)
            return min(base, 1.0)

        # Weak signal: just booking hint
        if has_booking_hint:
            return 0.5

        return 0.0

    if intent == "SERVICE_INFO":
        # Questions about services (not booking)
        has_service_kw = any(k in text for k in service_keywords)
        has_inquiry_kw = any(k in text for k in SERVICE_INQUIRY_KEYWORDS)
        has_previsit_kw = any(k in text for k in PREVISIT_INFO_KEYWORDS)
        has_booking_hint = any(k in text for k in BOOKING_HINTS)
        has_symptom_kw = any(k in text for k in SYMPTOM_KEYWORDS)
        has_food_kw = any(k in text for k in FOOD_CONTEXT_KEYWORDS)

        # Guard against obvious food-domain phrases (e.g. "kaj je za kosilo", "koleno bi jedel")
        if has_food_kw and not has_booking_hint and not has_appointment_kw:
            return 0.0

        # Strong signal: service + inquiry keyword (e.g., "kaj zdravi dermatolog?")
        if has_service_kw and has_inquiry_kw:
            return 0.9

        # Strong signal: service + pre-visit question (documents/preparation)
        if has_service_kw and has_previsit_kw:
            return 0.95

        # Urgent phrasing should route to URGENCY handler, not service info.
        if any(k in text for k in URGENCY_KEYWORDS):
            return 0.4

        # Strong signal: symptom report (e.g., "boli me glava")
        if has_symptom_kw:
            return 0.9

        # Medium signal: just inquiry keywords (e.g., "katere bolezni zdravite?")
        if has_inquiry_kw:
            if "storitve" in text and not has_service_kw and "ponujate" not in text:
                return 0.4
            return 0.85

        # Service keyword without appointment keyword -> info intent
        if has_service_kw and not has_appointment_kw:
            return 0.8

        # Service keyword with appointment keyword = likely BOOKING_APPOINTMENT
        if has_service_kw and has_appointment_kw:
            if not has_booking_hint and not any(k in text for k in {"naroč", "naroc", "rezerv", "termin"}):
                return 0.6
            return 0.3

        return 0.0

    if intent == "PRICE":
        if any(k in text for k in PRICE_KEYWORDS):
            return 0.9
        return 0.0

    if intent == "INFO":
        # Keep food-domain queries in safe generic assistance flow
        # (avoid uncertain fallback for messages like "kaj je za kosilo").
        if any(k in text for k in FOOD_CONTEXT_KEYWORDS):
            return 0.6
        if any(k in text for k in INFO_KEYWORDS) or "storitve" in text:
            return 0.8
        base = _score_question_marker(text)
        return min(base, 1.0)

    if intent == "URGENCY":
        if any(k in text for k in URGENCY_KEYWORDS):
            return 0.95
        return 0.0

    return 0.0


def detect_intents(message: str, service_map: Dict[str, list[str]] | None = None) -> Dict[str, float]:
    """Score all intents for given message."""
    service_keywords = _build_service_keywords(service_map)
    intents = [
        "BOOKING_APPOINTMENT",
        "SERVICE_INFO",
        "PRICE",
        "INFO",
        "URGENCY",
        "GREETING",
        "GOODBYE",
    ]
    return {intent: compute_confidence(message, intent, service_keywords=service_keywords) for intent in intents}


def pick_primary_secondary(scores: Dict[str, float]) -> Tuple[str, str | None, float]:
    """Pick primary and secondary intent from scores."""
    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    primary, primary_conf = sorted_scores[0]
    if primary_conf < 0.5:
        return "GENERAL", None, 0.0
    secondary = None
    if len(sorted_scores) > 1 and sorted_scores[1][1] >= 0.5:
        secondary = sorted_scores[1][0]
    return primary, secondary, primary_conf


def detect_service_type(message: str, service_map: Dict[str, list[str]] | None = None) -> str | None:
    """Public function to detect service type."""
    return _detect_service_type(message.lower(), service_map=service_map)
