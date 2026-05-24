from __future__ import annotations

from typing import Any

from app.services.clinic_config import get_clinic_config
from app.services.health_center_extensions import get_service_info, get_services
from app.services.routing.advice import advice_only_headache
from app.services.routing.locale_sl import QUESTION_MARKERS, SYMPTOM_MARKERS
from app.services.triage_service import get_triage_service


def looks_like_symptom_report(message: str) -> bool:
    lowered = message.lower()
    has_symptom = any(marker in lowered for marker in SYMPTOM_MARKERS)
    asks_question = any(marker in lowered for marker in QUESTION_MARKERS)
    return has_symptom and not asks_question


def match_unsupported_symptom(message: str, clinic_id: str | None = None) -> dict[str, Any] | None:
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


def specialist_quick_replies(clinic_id: str | None = None) -> list[dict[str, str]]:
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


def symptom_booking_nudge(service_key: str | None, clinic_id: str | None = None) -> str:
    key = (service_key or "").strip().lower()
    if not key:
        return "Če želite, lahko preverim prost termin pri ustreznem specialistu."
    info = get_service_info(key, clinic_id=clinic_id)
    if info:
        return f"Če želite, lahko takoj preverim prost termin za {info['name'].lower()}."
    return "Če želite, lahko takoj preverim prost termin pri ustreznem specialistu."


def append_nudge_if_missing(advice_text: str, nudge: str) -> str:
    lowered = advice_text.lower()
    if ("termin" in lowered and ("preverim" in lowered or "naro" in lowered)):
        return advice_text
    return f"{advice_text}\n\n{nudge}"


def looks_like_medical_statement(message: str) -> bool:
    lowered = message.lower()
    medical_cues = [
        "krv",
        "krvav",
        "krvavim",
        "nos",
        "diham",
        "duši",
        "dus",
        "nezavest",
        "omedlev",
        "bruham",
        "vrti",
        "vročina",
        "vrocina",
    ]
    return any(cue in lowered for cue in medical_cues)


def looks_like_previsit_question(message: str) -> bool:
    lowered = message.lower()
    # Only explicit "what do I bring / what do I need before the appointment" questions.
    # Do NOT include "mr", "rtg", "napotnic*" — those go to the LLM.
    previsit_keywords = [
        "izvid",
        "izvide",
        "izvidi",
        "pred pregledom",
        "s sabo",
        "moram prinesti",
        "prinesem",
    ]
    question_markers = ["?", "ali", "kaj", "moram", "potrebujem"]
    return any(k in lowered for k in previsit_keywords) and any(q in lowered for q in question_markers)


def looks_like_urgent_message(message: str) -> bool:
    lowered = message.lower()
    urgent_phrases = [
        "težko diham",
        "tezko diham",
        "bolečina v prs",
        "bolecina v prs",
        "krvavim",
        "krvavi",
        "nezavest",
        "omedlev",
    ]
    return any(p in lowered for p in urgent_phrases)


def previsit_guidance_response(service_key: str | None, clinic_id: str | None = None) -> str:
    service_name = None
    if service_key:
        info = get_service_info(service_key.lower(), clinic_id=clinic_id)
        if info:
            service_name = info.get("name")
    service_label = service_name or "pregled"
    return (
        f"Za {service_label.lower()} običajno priporočamo, da prinesete obstoječe izvide, "
        "seznam zdravil in osebni dokument. Če imate napotnico, jo prinesite s seboj.\n\n"
        "Če nimate vse dokumentacije, lahko vseeno pridete na pregled.\n\n"
        "Če želite, lahko takoj preverim prost termin."
    )


def looks_like_uncertain_help_request(message: str) -> bool:
    lowered = message.lower()
    signals = [
        "ne vem",
        "ne vem tocno",
        "ne vem točno",
        "nekaj ni ok",
        "nekaj ni v redu",
        "sam neki ni ok",
        "nisem prepričan",
    ]
    return any(sig in lowered for sig in signals)


def looks_like_medication_request(message: str) -> bool:
    lowered = message.lower()
    medication_keywords = [
        "tablete",
        "tableta",
        "zdravilo",
        "zdravila",
        "recept",
        "predpis",
        "antibiotik",
        "protiboleč",
        "protibolec",
        "analgetik",
    ]
    ask_markers = ["lahko", "dobim", "date", "izdate", "prodam", "prodajate", "?"]
    return any(k in lowered for k in medication_keywords) and any(a in lowered for a in ask_markers)


def quick_triage_fallback(message: str, clinic_id: str | None = None) -> str | None:
    if not (looks_like_symptom_report(message) or looks_like_medical_statement(message)):
        return None

    lowered = message.lower()
    if any(k in lowered for k in ["glava", "glavobol", "migrena"]):
        return append_nudge_if_missing(
            advice_only_headache(),
            symptom_booking_nudge(None, clinic_id=clinic_id),
        )

    try:
        triage = get_triage_service().quick_triage(message)
    except Exception:
        return None

    recommendation = str(triage.get("recommendation") or "").strip()
    disclaimer = str(triage.get("disclaimer") or "").strip()
    specialist = str(triage.get("specialist") or "").strip().lower()

    if not recommendation:
        return None

    parts: list[str] = [recommendation]
    if disclaimer:
        parts.append(disclaimer)

    if specialist:
        parts.append(symptom_booking_nudge(specialist, clinic_id=clinic_id))
    else:
        parts.append(
            "Če želite, lahko težavo opišete bolj natančno (npr. koža, sklepi, vid), "
            "da vas usmerim k ustreznemu specialistu."
        )

    return "\n\n".join(parts)

