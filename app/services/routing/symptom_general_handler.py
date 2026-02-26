from __future__ import annotations

from app.services.routing.unified_router import IntentType


def _looks_like_question_form_symptom(text: str) -> bool:
    lowered = (text or "").lower()
    symptom_cues = [
        "boli",
        "boleč",
        "bolec",
        "glavobol",
        "glava me boli",
        "bula",
        "bulo",
        "izpusc",
        "izpušč",
        "madez",
        "madež",
        "srbi",
        "pece",
        "peče",
        "krvavi",
        "krvavim",
        "otek",
        "oteklo",
        "vrocina",
        "vročina",
        "bruham",
        "vrti se",
        "tezko diham",
        "težko diham",
        "poskod",
        "poškod",
    ]
    return any(cue in lowered for cue in symptom_cues)


def should_handle_general_symptom_message(
    *,
    message: str,
    primary_intent: IntentType,
    service_type: str | None,
    in_flow: bool,
    looks_like_symptom_report,
    looks_like_medical_statement,
) -> bool:
    """
    Catch vague health/symptom messages before they fall into generic or booking prompts.
    Conservative guard: only when no concrete service is identified and user is not already in booking flow.
    """
    if in_flow:
        return False
    if service_type:
        return False
    if primary_intent not in {IntentType.GENERAL, IntentType.BOOKING_APPOINTMENT, IntentType.SERVICE_INFO}:
        return False

    text = (message or "").strip()
    if not text:
        return False

    return bool(
        looks_like_symptom_report(text)
        or looks_like_medical_statement(text)
        or _looks_like_question_form_symptom(text)
    )


def build_general_symptom_clarify_reply(*, triage_fallback: str | None) -> str:
    if triage_fallback and triage_fallback.strip():
        return triage_fallback.strip()
    return (
        "Na podlagi opisa ne morem zanesljivo določiti ustreznega specialista.\n\n"
        "Za začetek lahko pomaga počitek, dovolj tekočine in opazovanje simptomov. "
        "Če se stanje poslabša, traja več dni ali se pojavijo dodatni opozorilni znaki, "
        "je priporočljiv pregled pri zdravniku.\n\n"
        "To ni zdravniška diagnoza, ampak splošna usmeritev.\n\n"
        "Če želite, lahko težavo opišete bolj natančno (npr. koža, sklepi, vid), "
        "da vas usmerim k ustreznemu specialistu."
    )
