"""
Triage Service - Soft triage za usmerjanje k pravemu specialistu

POMEMBNO:
- NI diagnoza! Samo usmerjanje.
- Vedno: "Posvetujte se z zdravnikom"
- Nikoli: "Ni urgentno" ali "Ni potreben pregled"

FUNKCIONALNOST:
1. Symptom collection - strukturirana vprašanja
2. Specialist routing - usmerjanje k pravemu specialistu
3. Soft urgency indicators - brez diagnoze, samo priporočila

UPORABA:
    from app.services.triage_service import TriageService

    triage = TriageService()
    session = triage.start_triage_session(session_id)
    result = triage.process_response(session_id, "Boli me glava")
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import logging
import re

from app.services.routing.symptom_lexicon import (
    DERMATOLOGY_HINTS,
    OPHTHALMOLOGY_HINTS,
    ORTHOPEDICS_HINTS,
    URGENT_MEDICAL_HINTS,
)

logger = logging.getLogger(__name__)

# POMEMBNO: Vsi odgovori morajo vsebovati to opozorilo
MEDICAL_DISCLAIMER = """
 **Opomba**: To ni zdravniška diagnoza. Za natančno oceno se vedno posvetujte z zdravnikom.
"""


class TriageState(Enum):
    """Stanja triage procesa"""
    INITIAL = "initial"                 # Začetek
    COLLECTING_SYMPTOMS = "collecting"  # Zbiranje simptomov
    COLLECTING_DURATION = "duration"    # Trajanje simptomov
    COLLECTING_INTENSITY = "intensity"  # Intenzivnost
    COLLECTING_HISTORY = "history"      # Zgodovina
    COMPLETED = "completed"             # Zaključeno


class SymptomIntensity(Enum):
    """Intenzivnost simptomov"""
    MILD = 1        # Blago
    MODERATE = 2    # Zmerno
    SEVERE = 3      # Hudo
    EMERGENCY = 4   # Urgentno


@dataclass
class TriageSession:
    """Seja triage procesa"""
    session_id: str
    state: TriageState = TriageState.INITIAL
    symptoms: List[str] = field(default_factory=list)
    duration_days: Optional[int] = None
    intensity: Optional[SymptomIntensity] = None
    additional_info: Dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None


# Triage vprašanja
TRIAGE_QUESTIONS = {
    TriageState.INITIAL: {
        "question": "Kaj vas muči? Opišite vaše simptome.",
        "follow_up": "Lahko mi poveste več o tem, kaj vas muči?"
    },
    TriageState.COLLECTING_DURATION: {
        "question": "Kako dolgo že imate te težave?",
        "options": ["Danes", "Nekaj dni", "Teden dni", "Mesec ali več"]
    },
    TriageState.COLLECTING_INTENSITY: {
        "question": "Kako močne so vaše težave na lestvici 1-10?",
        "options": ["1-3 (blago)", "4-6 (zmerno)", "7-8 (hudo)", "9-10 (zelo hudo)"]
    },
    TriageState.COLLECTING_HISTORY: {
        "question": "Ali ste že kdaj imeli podobne težave?",
        "options": ["Da, večkrat", "Da, enkrat", "Ne, prvič"]
    }
}

# Simptom → specialist mapping
SYMPTOM_SPECIALIST_MAP = {
    # Dermatolog
    r"(\bkoža\b|\bkozi?\b|kožn|kozn|izpuščaj|izpuscaj|akne|mozolj|bradavic|luščenj|luscenj|srbi|srbe|peče kož|pece koz|bula|bulo|bulica|zatrdlin|izboklin)": {
        "specialist": "dermatolog",
        "confidence": 0.9,
        "message": "Za težave s kožo priporočam pregled pri dermatologu."
    },
    r"(znamenj|madež|pega|pigment)": {
        "specialist": "dermatolog",
        "confidence": 0.95,
        "message": "Za pregled kožnih znamenj priporočam obisk pri dermatologu.",
        "priority": True
    },

    # Ortoped
    r"(kolen|sklep|hrbten|hrbet|križ|ram[ae]|gleženj|zapest)": {
        "specialist": "ortoped",
        "confidence": 0.9,
        "message": "Za težave s sklepi in hrbtenico priporočam ortopedski pregled."
    },
    r"(zlom|poškodb|zvin)": {
        "specialist": "ortoped",
        "confidence": 0.95,
        "message": "Za poškodbe priporočam obisk pri ortopedu.",
        "priority": True
    },

    # Okulist
    r"(\boči\b|\boci\b|\bočes\w*|\boces\w*|\bvid\w*|gledl|zamegljen|zamegljeno|očala|ocala|leč|lec|oftalm|okul)": {
        "specialist": "okulist",
        "confidence": 0.9,
        "message": "Za očesne težave priporočam okulistični pregled."
    },

    # Urgentno (vedno napoti k zdravniku!)
    r"(krv|krvav|nezavest|dihanj|prsih|srčn|omedlev)": {
        "specialist": "urgenca",
        "confidence": 1.0,
        "message": " POMEMBNO: Pri teh simptomih priporočam takojšnjo medicinsko pomoč. Pokličite 112 ali obiščite urgentni center.",
        "urgent": True
    }
}


class TriageService:
    """Service za soft triage - usmerjanje k pravemu specialistu."""

    def __init__(self):
        self.sessions: Dict[str, TriageSession] = {}

    # ================================================================
    # SESSION MANAGEMENT
    # ================================================================

    def start_triage_session(self, session_id: str) -> Dict[str, Any]:
        """
        Začne novo triage sejo.

        Args:
            session_id: ID seje

        Returns:
            Začetno vprašanje in metadata
        """
        session = TriageSession(session_id=session_id)
        self.sessions[session_id] = session

        return {
            "session_id": session_id,
            "state": session.state.value,
            "question": TRIAGE_QUESTIONS[TriageState.INITIAL]["question"],
            "started_at": session.started_at
        }

    def get_session(self, session_id: str) -> Optional[TriageSession]:
        """Vrne obstoječo sejo."""
        return self.sessions.get(session_id)

    def end_session(self, session_id: str) -> bool:
        """Zaključi sejo."""
        if session_id in self.sessions:
            self.sessions[session_id].completed_at = datetime.now().isoformat()
            del self.sessions[session_id]
            return True
        return False

    # ================================================================
    # SYMPTOM ANALYSIS
    # ================================================================

    def analyze_symptoms(self, text: str) -> Dict[str, Any]:
        """
        Analizira simptome iz besedila.

        Args:
            text: Opis simptomov

        Returns:
            {
                "detected_symptoms": [...],
                "recommended_specialist": str,
                "confidence": float,
                "message": str,
                "is_urgent": bool
            }
        """
        text_lower = text.lower()
        matches = []

        for pattern, info in SYMPTOM_SPECIALIST_MAP.items():
            if re.search(pattern, text_lower):
                matches.append({
                    "specialist": info["specialist"],
                    "confidence": info["confidence"],
                    "message": info["message"],
                    "urgent": info.get("urgent", False),
                    "priority": info.get("priority", False)
                })

        # Shared keyword fallback to keep triage and routing aligned.
        if not matches:
            if any(token in text_lower for token in URGENT_MEDICAL_HINTS):
                matches.append({
                    "specialist": "urgenca",
                    "confidence": 1.0,
                    "message": " POMEMBNO: Pri teh simptomih priporočam takojšnjo medicinsko pomoč. Pokličite 112 ali obiščite urgentni center.",
                    "urgent": True,
                    "priority": True,
                })
            elif any(token in text_lower for token in DERMATOLOGY_HINTS):
                matches.append({
                    "specialist": "dermatolog",
                    "confidence": 0.9,
                    "message": "Za težave s kožo priporočam pregled pri dermatologu.",
                    "urgent": False,
                    "priority": False,
                })
            elif any(token in text_lower for token in ORTHOPEDICS_HINTS):
                matches.append({
                    "specialist": "ortoped",
                    "confidence": 0.9,
                    "message": "Za težave s sklepi in hrbtenico priporočam ortopedski pregled.",
                    "urgent": False,
                    "priority": False,
                })
            elif any(token in text_lower for token in OPHTHALMOLOGY_HINTS):
                matches.append({
                    "specialist": "okulist",
                    "confidence": 0.9,
                    "message": "Za očesne težave priporočam okulistični pregled.",
                    "urgent": False,
                    "priority": False,
                })

        # Sort by confidence and priority
        matches.sort(key=lambda x: (x.get("urgent", False), x.get("priority", False), x["confidence"]), reverse=True)

        if not matches:
            return {
                "detected_symptoms": [],
                "recommended_specialist": None,
                "confidence": 0,
                "message": "Na podlagi opisa ne morem določiti specialista. Za več informacij se posvetujte z osebnim zdravnikom.",
                "is_urgent": False
            }

        top_match = matches[0]

        return {
            "detected_symptoms": [m["specialist"] for m in matches],
            "recommended_specialist": top_match["specialist"],
            "confidence": top_match["confidence"],
            "message": top_match["message"],
            "is_urgent": top_match.get("urgent", False),
            "all_matches": matches[:3]  # Top 3
        }

    # ================================================================
    # TRIAGE PROCESS
    # ================================================================

    def process_response(
        self,
        session_id: str,
        response: str
    ) -> Dict[str, Any]:
        """
        Procesira uporabnikov odgovor in nadaljuje triage.

        Args:
            session_id: ID seje
            response: Uporabnikov odgovor

        Returns:
            {
                "state": str,
                "question": str or None,
                "analysis": {...} or None,
                "recommendation": str or None,
                "completed": bool
            }
        """
        session = self.get_session(session_id)

        if not session:
            # Start new session
            return self.start_triage_session(session_id)

        result = {
            "session_id": session_id,
            "state": session.state.value,
            "question": None,
            "analysis": None,
            "recommendation": None,
            "completed": False
        }

        # Process based on current state
        if session.state == TriageState.INITIAL:
            # Analiziraj simptome
            analysis = self.analyze_symptoms(response)
            session.symptoms = [response]
            session.additional_info["initial_analysis"] = analysis

            # Če je urgentno, takoj zaključi
            if analysis.get("is_urgent"):
                session.state = TriageState.COMPLETED
                result["state"] = session.state.value
                result["completed"] = True
                result["analysis"] = analysis
                result["recommendation"] = self._build_recommendation(session, analysis)
                self.end_session(session_id)
                return result

            # Nadaljuj z vprašanji
            session.state = TriageState.COLLECTING_DURATION
            result["state"] = session.state.value
            result["question"] = TRIAGE_QUESTIONS[TriageState.COLLECTING_DURATION]["question"]
            result["options"] = TRIAGE_QUESTIONS[TriageState.COLLECTING_DURATION].get("options")
            result["analysis"] = analysis

        elif session.state == TriageState.COLLECTING_DURATION:
            # Parse duration
            session.duration_days = self._parse_duration(response)
            session.state = TriageState.COLLECTING_INTENSITY
            result["state"] = session.state.value
            result["question"] = TRIAGE_QUESTIONS[TriageState.COLLECTING_INTENSITY]["question"]
            result["options"] = TRIAGE_QUESTIONS[TriageState.COLLECTING_INTENSITY].get("options")

        elif session.state == TriageState.COLLECTING_INTENSITY:
            # Parse intensity
            session.intensity = self._parse_intensity(response)

            # Če je zelo hudo, skip history in zaključi
            if session.intensity and session.intensity.value >= SymptomIntensity.SEVERE.value:
                session.state = TriageState.COMPLETED
            else:
                session.state = TriageState.COLLECTING_HISTORY

            if session.state == TriageState.COMPLETED:
                analysis = session.additional_info.get("initial_analysis", {})
                result["completed"] = True
                result["recommendation"] = self._build_recommendation(session, analysis)
                self.end_session(session_id)
            else:
                result["question"] = TRIAGE_QUESTIONS[TriageState.COLLECTING_HISTORY]["question"]
                result["options"] = TRIAGE_QUESTIONS[TriageState.COLLECTING_HISTORY].get("options")

            result["state"] = session.state.value

        elif session.state == TriageState.COLLECTING_HISTORY:
            # Save history info
            session.additional_info["history"] = response
            session.state = TriageState.COMPLETED
            result["state"] = session.state.value
            result["completed"] = True

            analysis = session.additional_info.get("initial_analysis", {})
            result["recommendation"] = self._build_recommendation(session, analysis)
            self.end_session(session_id)

        return result

    def _parse_duration(self, response: str) -> int:
        """Parse trajanje iz odgovora."""
        response_lower = response.lower()

        if "danes" in response_lower or "zdaj" in response_lower:
            return 0
        elif "nekaj dni" in response_lower or "par dni" in response_lower:
            return 3
        elif "teden" in response_lower:
            return 7
        elif "mesec" in response_lower or "več" in response_lower:
            return 30
        else:
            # Try to parse number
            numbers = re.findall(r'\d+', response)
            if numbers:
                return int(numbers[0])
            return 1

    def _parse_intensity(self, response: str) -> SymptomIntensity:
        """Parse intenzivnost iz odgovora."""
        response_lower = response.lower()

        # Check for numbers
        numbers = re.findall(r'\d+', response)
        if numbers:
            num = int(numbers[0])
            if num <= 3:
                return SymptomIntensity.MILD
            elif num <= 6:
                return SymptomIntensity.MODERATE
            elif num <= 8:
                return SymptomIntensity.SEVERE
            else:
                return SymptomIntensity.EMERGENCY

        # Check for keywords
        if "blago" in response_lower:
            return SymptomIntensity.MILD
        elif "zmerno" in response_lower:
            return SymptomIntensity.MODERATE
        elif "hudo" in response_lower or "močno" in response_lower:
            return SymptomIntensity.SEVERE
        elif "zelo" in response_lower or "neznosno" in response_lower:
            return SymptomIntensity.EMERGENCY

        return SymptomIntensity.MODERATE

    def _build_recommendation(
        self,
        session: TriageSession,
        analysis: Dict
    ) -> str:
        """Zgradi končno priporočilo."""
        lines = []

        # Specialist recommendation
        specialist = analysis.get("recommended_specialist")
        message = analysis.get("message", "")

        if specialist == "urgenca":
            lines.append(" **URGENTNO**")
            lines.append("")
            lines.append(message)
        else:
            lines.append(" **Priporočilo**")
            lines.append("")
            lines.append(message)

            # Add duration/intensity context
            if session.duration_days is not None:
                if session.duration_days > 7:
                    lines.append("")
                    lines.append("Ker težave trajajo dlje časa, priporočam čimprejšnji pregled.")

            if session.intensity and session.intensity.value >= SymptomIntensity.SEVERE.value:
                lines.append("")
                lines.append("Glede na jakost simptomov priporočam pregled v naslednjih dneh.")

        # Always add disclaimer
        lines.append("")
        lines.append(MEDICAL_DISCLAIMER.strip())

        # CTA
        lines.append("")
        lines.append("Želite rezervirati termin?")

        return "\n".join(lines)

    # ================================================================
    # QUICK TRIAGE (single-step)
    # ================================================================

    def quick_triage(self, symptoms_text: str) -> Dict[str, Any]:
        """
        Izvede hitro triažo brez multi-step procesa.

        Args:
            symptoms_text: Opis simptomov

        Returns:
            Priporočilo in analiza
        """
        analysis = self.analyze_symptoms(symptoms_text)

        return {
            "analysis": analysis,
            "recommendation": analysis.get("message", ""),
            "disclaimer": MEDICAL_DISCLAIMER.strip(),
            "specialist": analysis.get("recommended_specialist"),
            "is_urgent": analysis.get("is_urgent", False)
        }


# Singleton instance
_triage_service = None


def get_triage_service() -> TriageService:
    """Vrne singleton instance."""
    global _triage_service
    if _triage_service is None:
        _triage_service = TriageService()
    return _triage_service
