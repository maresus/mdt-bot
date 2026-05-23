"""
Out-of-Domain (OOD) Policy Guard for Zdravstveni Center AI

This module provides centralized OOD detection and response handling
for the healthcare center chatbot.

Key differences from farm chatbots:
- Medical questions within offered services are IN-DOMAIN
- Medical questions outside offered specialties (e.g., neurology) are OOD_MEDICAL_OUTSIDE
- General non-medical OOD (traktor, bitcoin) same as other bots

Based on the spec:
- OOD_HARD: Clearly outside domain (traktor, avto, bitcoin, politika)
- OOD_MEDICAL_OUTSIDE: Medical questions outside clinic's specialties
- OOD_SOFT: Borderline cases detected via RAG similarity threshold

Priority: ood_hard > ood_medical_outside > ood_soft
"""
from __future__ import annotations

import logging
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION (via environment variables)
# ─────────────────────────────────────────────────────────────────────────────

OOD_HARD_ENABLED = os.getenv("OOD_HARD_ENABLED", "false").lower() == "true"
OOD_MEDICAL_ENABLED = os.getenv("OOD_MEDICAL_ENABLED", "false").lower() == "true"
OOD_SOFT_ENABLED = os.getenv("OOD_SOFT_ENABLED", "false").lower() == "true"
OOD_SOFT_DRY_RUN = os.getenv("OOD_SOFT_DRY_RUN", "true").lower() == "true"
OOD_THRESHOLD = max(0.0, min(1.0, float(os.getenv("OOD_THRESHOLD", "0.45"))))
OOD_LOG_SAMPLES = os.getenv("OOD_LOG_SAMPLES", "true").lower() == "true"
OOD_LOG_SAMPLE_RATE = max(0.0, min(1.0, float(os.getenv("OOD_LOG_SAMPLE_RATE", "0.2"))))
OOD_MIXED_SPLIT_ENABLED = os.getenv("OOD_MIXED_SPLIT_ENABLED", "true").lower() == "true"

# Minimum input length for OOD classification
MIN_OOD_INPUT_LENGTH = 4

# Log file path
OOD_LOG_PATH = Path("data/ood_samples.jsonl")


class OODLevel(str, Enum):
    """OOD classification levels."""
    HARD = "ood_hard"
    MEDICAL_OUTSIDE = "ood_medical_outside"  # Medical but outside clinic's specialties
    SOFT = "ood_soft"
    NONE = "none"


@dataclass
class OODResult:
    """Result of OOD classification."""
    is_ood: bool
    level: OODLevel
    confidence: float
    reason: str
    response: Optional[str] = None
    in_domain_parts: Optional[list[str]] = None


# ─────────────────────────────────────────────────────────────────────────────
# OOD HARD KEYWORDS (completely unrelated to healthcare)
# ─────────────────────────────────────────────────────────────────────────────

OOD_HARD_KEYWORDS = frozenset({
    # Transport / vehicles
    "traktor", "avto servis", "avtomehanik", "vulkanizer",
    # Finance / crypto
    "bitcoin", "crypto", "kripto", "delnice", "investic",
    # Politics / news
    "politika", "politik", "volit", "volitve", "vlada", "predsednik",
    "stranka", "trump", "biden",
    # Real estate
    "nepremičnin", "nepremicnin", "stanovanje",
    # Tech / IT
    "programir", "python", "javascript", "linux",
    # Sports results
    "nogomet rezultat", "košarka rezultat",
    # Completely unrelated
    "recept za", "kuhanje", "pečenje", "kmetij", "turizem",
    "hotel rezerv", "letalo",
})

# ─────────────────────────────────────────────────────────────────────────────
# OOD MEDICAL OUTSIDE SCOPE (medical but not offered at this clinic)
# These are medical topics the chatbot should NOT advise on
# ─────────────────────────────────────────────────────────────────────────────

OOD_MEDICAL_OUTSIDE_KEYWORDS = frozenset({
    # Specialties typically not offered at aesthetic/dermatology clinics
    "nevrolog", "nevrologija", "nevrokirurg",
    "kardiolog", "kardiologija", "srčni",
    "ortoped", "ortopedija", "zlom", "zlomljen",
    "psihiater", "psihiatrij", "depresij", "anksioznost",
    "onkolog", "onkologija", "rak", "tumor", "kemoterapij",
    "pediater", "pediatrija",
    "ginekolog", "ginekologija", "nosečnost", "porod",
    "urolog", "urologija",
    "okulist", "oftalmolog", "oko operacij",
    "zobozdrav", "stomatolog", "zob",
    # Emergency situations
    "reanimacij", "srčni infarkt", "možganska kap",
    "huda bolečina", "nezavest",
    # Prescription medications (outside chatbot scope)
    "antibiotik recept", "morfij", "opioid",
})

# ─────────────────────────────────────────────────────────────────────────────
# IN-DOMAIN KEYWORDS (services offered at Zdravstveni Center)
# ─────────────────────────────────────────────────────────────────────────────

IN_DOMAIN_KEYWORDS = frozenset({
    # Appointment booking
    "naroč", "termin", "rezerv", "pregled", "posvet",
    # Aesthetic services
    "botoks", "botox", "filer", "hialuro", "mezoterapij",
    "estetsk", "pomladitev", "gube", "polnilo",
    # Dermatology
    "dermatolog", "dermatologija", "koža", "kožn",
    "akne", "pigmentacij", "melanom", "madež",
    "izpuščaj", "srbenje", "ekcem", "luskavic", "psoriaz",
    # Laser treatments
    "laser", "epilacij", "odstranjevanje dlak",
    "žilice", "razširjene žile", "kapilare",
    # Body treatments
    "celulite", "oblikovanje telesa", "hujšanje",
    "lipoliz", "kriolipoliz",
    # Hair
    "lasje", "izpadanje las", "presaditev las", "prp",
    # General clinic info
    "cena", "cenik", "koliko stane", "koliko je",
    "lokacij", "naslov", "kje ste", "parkir",
    "delovni čas", "odprto", "ura",
    "kontakt", "telefon", "email",
    "ekipa", "zdravnik", "specialist",
    # Insurance
    "zavarovanje", "dopolnilno", "povračilo", "plačilo",
})

# ─────────────────────────────────────────────────────────────────────────────
# OOD RESPONSE TEMPLATES
# ─────────────────────────────────────────────────────────────────────────────

OOD_HARD_RESPONSES = [
    "O tem nimam informacij — sem specializiran za MDT&T.\n"
    "Lahko vam pomagam z naročanjem na pregled, informacijami o storitvah ali cenah.\n"
    "Kako vam lahko pomagam?",

    "To je izven mojega področja. Sem tu za pomoč z zdravstvenimi storitvami našega centra.\n"
    "Vas zanima naročanje ali informacije o naših storitvah?",

    "Žal o tem ne morem pomagati. Moje znanje zajema storitve Zdravstvenega centra — "
    "dermatologija, estetski posegi, laserski tretmaji.\n"
    "Pri čem vam lahko pomagam?",
]

OOD_MEDICAL_OUTSIDE_RESPONSES = [
    "To področje ni v naši ponudbi — priporočam posvet s splošnim zdravnikom ali ustreznim specialistom.\n"
    "Pri nas pa lahko pomagam z diagnostičnimi preiskavami (MR, RTG, UZ).\n"
    "Vas zanima kaj od tega?",

    "Za to vrsto zdravstvene težave se prosim obrnite na ustreznega specialista.\n"
    "Naš center se ukvarja z diagnostičnimi preiskavami MR, RTG in UZ.\n"
    "Vam lahko pomagam z naročanjem na enega od naših pregledov?",

    "To presega naše specializacije — za takšna vprašanja obiščite svojega zdravnika.\n"
    "Z veseljem pa pomagam z informacijami o naših diagnostičnih preiskavah (MR, RTG, UZ)!",
]

OOD_SOFT_RESPONSES = [
    "Nisem povsem prepričan, da razumem vaše vprašanje.\n"
    "Sem specializiran za MDT&T — naročanje, storitve, cene.\n"
    "Mi lahko pojasnite, kaj vas zanima?",

    "To vprašanje je morda izven mojega znanja.\n"
    "Lahko pomagam z naročanjem na pregled ali informacijami o naših storitvah.\n"
    "Kaj od tega vas zanima?",

    "Nisem prepričan, da imam te informacije.\n"
    "Povejte mi več o tem, kaj potrebujete, pa poskusim pomagati!",
]


def _get_random_response(responses: list[str]) -> str:
    """Return a random response from the list."""
    return random.choice(responses)


def _log_ood_sample(
    message: str,
    level: OODLevel,
    dry_run: bool = False,
    confidence: float = 0.0,
    reason: str = "",
) -> None:
    """Log OOD sample with sampling rate control."""
    if not OOD_LOG_SAMPLES:
        return
    if random.random() > OOD_LOG_SAMPLE_RATE:
        return

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": message[:500],
        "level": level.value,
        "confidence": confidence,
        "reason": reason,
        "dry_run": dry_run,
    }

    try:
        OOD_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with OOD_LOG_PATH.open("a", encoding="utf-8") as f:
            import json
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Failed to log OOD sample: {e}")


def _has_keywords(text: str, keywords: frozenset[str]) -> tuple[bool, list[str]]:
    """Check if text contains any keywords."""
    text_lower = text.lower()
    matched = [kw for kw in keywords if kw in text_lower]
    return bool(matched), matched


def _detect_mixed_input(message: str) -> tuple[list[str], list[str]]:
    """Detect mixed input (OOD + in-domain parts)."""
    sentences = re.split(r'[.?!]+', message)
    ood_parts = []
    in_domain_parts = []

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        has_ood, _ = _has_keywords(sentence, OOD_HARD_KEYWORDS)
        has_in_domain, _ = _has_keywords(sentence, IN_DOMAIN_KEYWORDS)

        if has_ood and not has_in_domain:
            ood_parts.append(sentence)
        elif has_in_domain:
            in_domain_parts.append(sentence)

    return ood_parts, in_domain_parts


def classify_ood(
    message: str,
    rag_similarity: Optional[float] = None,
    session_data: Optional[dict[str, Any]] = None,
) -> OODResult:
    """
    Classify message as OOD or in-domain.

    Args:
        message: User message to classify
        rag_similarity: Optional RAG similarity score (0-1)
        session_data: Optional session data for context

    Returns:
        OODResult with classification details
    """
    # Skip short inputs
    if len(message.strip()) < MIN_OOD_INPUT_LENGTH:
        return OODResult(
            is_ood=False,
            level=OODLevel.NONE,
            confidence=0.0,
            reason="Short input - skipped OOD check",
        )

    text_lower = message.lower()

    # Check if user is mid-booking - be more permissive
    is_booking = False
    if session_data:
        flow = session_data.get("flow_type")
        step = session_data.get("step")
        is_booking = flow == "appointment" and step is not None

    if is_booking:
        has_hard, matched_hard = _has_keywords(text_lower, OOD_HARD_KEYWORDS)
        if has_hard and OOD_HARD_ENABLED:
            return OODResult(
                is_ood=True,
                level=OODLevel.HARD,
                confidence=0.95,
                reason=f"OOD hard keyword during booking: {matched_hard}",
                response=_get_random_response(OOD_HARD_RESPONSES),
            )
        return OODResult(
            is_ood=False,
            level=OODLevel.NONE,
            confidence=0.0,
            reason="Mid-booking - OOD check relaxed",
        )

    # ── PRIORITY 1: OOD_HARD ────────────────────────────────────────────────
    if OOD_HARD_ENABLED:
        has_hard, matched_hard = _has_keywords(text_lower, OOD_HARD_KEYWORDS)
        if has_hard:
            if OOD_MIXED_SPLIT_ENABLED:
                ood_parts, in_domain_parts = _detect_mixed_input(message)
                if in_domain_parts:
                    _log_ood_sample(message, OODLevel.HARD, confidence=0.9, reason="mixed_input")
                    return OODResult(
                        is_ood=True,
                        level=OODLevel.HARD,
                        confidence=0.9,
                        reason=f"Mixed input: OOD={matched_hard}",
                        response=None,
                        in_domain_parts=in_domain_parts,
                    )

            _log_ood_sample(message, OODLevel.HARD, confidence=0.95, reason=str(matched_hard))
            return OODResult(
                is_ood=True,
                level=OODLevel.HARD,
                confidence=0.95,
                reason=f"OOD hard keywords: {matched_hard}",
                response=_get_random_response(OOD_HARD_RESPONSES),
            )

    # ── PRIORITY 2: OOD_MEDICAL_OUTSIDE ─────────────────────────────────────
    if OOD_MEDICAL_ENABLED:
        has_medical_outside, matched_medical = _has_keywords(text_lower, OOD_MEDICAL_OUTSIDE_KEYWORDS)
        if has_medical_outside:
            _log_ood_sample(message, OODLevel.MEDICAL_OUTSIDE, confidence=0.9, reason=str(matched_medical))
            return OODResult(
                is_ood=True,
                level=OODLevel.MEDICAL_OUTSIDE,
                confidence=0.9,
                reason=f"Medical outside clinic scope: {matched_medical}",
                response=_get_random_response(OOD_MEDICAL_OUTSIDE_RESPONSES),
            )

    # ── PRIORITY 3: OOD_SOFT (RAG similarity) ───────────────────────────────
    if OOD_SOFT_ENABLED and rag_similarity is not None:
        if rag_similarity < OOD_THRESHOLD:
            has_in_domain, _ = _has_keywords(text_lower, IN_DOMAIN_KEYWORDS)

            if not has_in_domain:
                if OOD_SOFT_DRY_RUN:
                    _log_ood_sample(
                        message, OODLevel.SOFT,
                        dry_run=True,
                        confidence=1.0 - rag_similarity,
                        reason=f"RAG similarity {rag_similarity:.2f} < {OOD_THRESHOLD}",
                    )
                    return OODResult(
                        is_ood=False,
                        level=OODLevel.SOFT,
                        confidence=1.0 - rag_similarity,
                        reason=f"OOD soft (dry run): RAG similarity {rag_similarity:.2f}",
                    )
                else:
                    _log_ood_sample(
                        message, OODLevel.SOFT,
                        confidence=1.0 - rag_similarity,
                        reason=f"RAG similarity {rag_similarity:.2f} < {OOD_THRESHOLD}",
                    )
                    return OODResult(
                        is_ood=True,
                        level=OODLevel.SOFT,
                        confidence=1.0 - rag_similarity,
                        reason=f"Low RAG similarity: {rag_similarity:.2f}",
                        response=_get_random_response(OOD_SOFT_RESPONSES),
                    )

    # ── NO OOD DETECTED ─────────────────────────────────────────────────────
    return OODResult(
        is_ood=False,
        level=OODLevel.NONE,
        confidence=0.0,
        reason="In-domain",
    )


def get_mixed_response(ood_result: OODResult, in_domain_response: str) -> str:
    """Generate response for mixed input."""
    if not ood_result.in_domain_parts:
        return ood_result.response or _get_random_response(OOD_HARD_RESPONSES)

    ood_acknowledgment = random.choice([
        "O prvem delu vašega vprašanja nimam informacij — to ni moje področje.",
        "Za del vašega vprašanja nimam podatkov.",
        "Žal ne morem pomagati z vsem, kar sprašujete.",
    ])

    return f"{ood_acknowledgment}\n\n{in_domain_response}"


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def check_ood(
    message: str,
    rag_similarity: Optional[float] = None,
    session_data: Optional[dict[str, Any]] = None,
) -> OODResult:
    """Main entry point for OOD checking."""
    return classify_ood(message, rag_similarity, session_data)
