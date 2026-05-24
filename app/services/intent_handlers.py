from __future__ import annotations
from typing import Any, Callable, Optional

from app.services.routing.unified_router import IntentType


def handle_greeting_goodbye_urgency(
    *,
    intent: IntentType,
    message: str,
    clinic_id: str | None,
    get_response: Callable[..., str],
    looks_like_urgent_message: Callable[[str], bool],
) -> Optional[str]:
    if intent == IntentType.GREETING:
        return get_response("general.greeting", clinic_id=clinic_id)
    if intent == IntentType.GOODBYE:
        return get_response("general.goodbye", clinic_id=clinic_id)
    if intent == IntentType.URGENCY:
        return get_response("general.urgency", clinic_id=clinic_id)
    if looks_like_urgent_message(message):
        return get_response("general.urgency", clinic_id=clinic_id)
    return None


def handle_service_info_intent(
    *,
    intent: IntentType,
    message: str,
    clinic_id: str | None,
    session_id: str,
    current_step: str | None,
    decision_service: Optional[str],
    state_mgr: Any,
    appointment_state: dict[str, Any],
    is_in_flow: Callable[[str], bool],
    extract_service_type: Callable[..., Optional[str]],
    start_flow: Callable[..., None],
    transition_to_booking: Callable[[Any, Optional[str], dict[str, Any]], None],
    flow_type_appointment: Any,
    flow_step_date: Any,
    extract_date_from_message: Callable[[str], Optional[str]],
    get_response: Callable[..., str],
    looks_like_previsit_question: Callable[[str], bool],
    previsit_guidance_response: Callable[[Optional[str], Optional[str]], str],
    looks_like_symptom_report: Callable[[str], bool],
    symptom_booking_nudge: Callable[[Optional[str], Optional[str]], str],
    append_nudge_if_missing: Callable[[str, str], str],
    advice_only: Callable[[Optional[str]], str],
    advice_only_headache: Callable[[], str],
    quick_triage_fallback: Callable[[str, Optional[str]], Optional[str]],
    service_info_response: Callable[[Optional[str], Optional[str]], Optional[str]],
    get_info_response: Callable[[str, Optional[str]], str],
    service_price_info: Callable[[Optional[str], Optional[str]], str],
    info_key_services: str,
) -> Optional[str]:
    if intent != IntentType.SERVICE_INFO:
        return None

    if is_in_flow(session_id) and current_step == "reason":
        return None

    if is_in_flow(session_id) and current_step in {"service", "select_service"}:
        selected_service = extract_service_type(message, clinic_id=clinic_id) or decision_service
        if selected_service:
            transition_to_booking(state_mgr, selected_service, appointment_state)
            start_flow(session_id, flow_type_appointment, flow_step_date)
            state_mgr.clear_context_key("suggested_service")
            if extract_date_from_message(message):
                return None
            return get_response(
                "booking.start_with_date",
                clinic_id=clinic_id,
                service_type=selected_service.lower(),
            )

    service = decision_service

    # Spodbujevalnik / pacemaker — absolutna blokada za MR
    _lowered_msg = message.lower()
    if any(w in _lowered_msg for w in ["spodbujevalnik", "spodbujevalnika", "defibrilator", "pacemaker"]):
        return (
            "Osebe s srčnim spodbujevalnikom ali defibrilatorjem MR preiskav žal ne morejo opraviti. "
            "Prosimo, posvetujte se z vašim zdravnikom ali nas pokličite na ☎️ 02 23 53 552."
        )

    if looks_like_previsit_question(message):
        return previsit_guidance_response(service, clinic_id=clinic_id)

    awaiting_price_service = bool(state_mgr.get_context_value("awaiting_price_service"))
    if service and awaiting_price_service:
        state_mgr.clear_context_key("awaiting_price_service")
        return service_price_info(service.lower(), clinic_id=clinic_id)

    if service:
        state_mgr.set_context_value("suggested_service", service)
        booking_push_words = (
            "naro",
            "termin",
            "rezerv",
            "vrzi",
            "vrži",
            "naroči me",
            "naroci me",
            "book",
        )
        lowered = message.lower()
        if any(word in lowered for word in booking_push_words):
            transition_to_booking(state_mgr, service, appointment_state)
            start_flow(session_id, flow_type_appointment, flow_step_date)
            state_mgr.clear_context_key("suggested_service")
            if extract_date_from_message(message):
                return None
            return get_response(
                "booking.start_with_date",
                clinic_id=clinic_id,
                service_type=service.lower(),
            )
        if looks_like_symptom_report(message):
            nudge = symptom_booking_nudge(service, clinic_id=clinic_id)
            return append_nudge_if_missing(advice_only(service), nudge)

    if looks_like_symptom_report(message) and not service:
        triage_fallback = quick_triage_fallback(message, clinic_id=clinic_id)
        if triage_fallback:
            return triage_fallback
        lowered = message.lower()
        if any(k in lowered for k in ["glava", "glavobol", "migrena"]):
            return advice_only_headache()
        return append_nudge_if_missing(
            advice_only(None),
            symptom_booking_nudge(None, clinic_id=clinic_id),
        )

    service_reply = service_info_response(service, clinic_id)
    if service_reply:
        return service_reply
    return get_info_response(info_key_services, clinic_id=clinic_id)


def handle_unsupported_symptom_intent(
    *,
    intent: IntentType,
    message: str,
    clinic_id: str | None,
    session_id: str,
    state_mgr: Any,
    is_in_flow: Callable[[str], bool],
    match_unsupported_symptom: Callable[[str, Optional[str]], Optional[dict[str, Any]]],
    get_response: Callable[..., str],
    get_domain_response: Callable[..., Any],
) -> Optional[str]:
    if intent != IntentType.UNSUPPORTED_SYMPTOM:
        return None

    unsupported = match_unsupported_symptom(message, clinic_id=clinic_id)
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
        if not quick_replies:
            quick_replies = [
                {"label": "Da, predlagajte specialista", "value": "DA"},
                {"label": "Ne, hvala", "value": "NE"},
            ]
        if isinstance(quick_replies, dict):
            quick_replies = [quick_replies]
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


def handle_price_intent(
    *,
    intent: IntentType,
    clinic_id: str | None,
    decision_service: Optional[str],
    suggested_service: Optional[str],
    appointment_state: dict[str, Any],
    state_mgr: Any,
    service_price_info: Callable[[Optional[str], Optional[str]], str],
    extract_service_type: Callable[[str, Optional[str]], Optional[str]],
    rag_info_answer: Callable[[str, str, Optional[str]], str],
    message: str,
    info_key_prices: str,
) -> Optional[str]:
    if intent != IntentType.PRICE:
        return None

    service = decision_service or suggested_service or appointment_state.get("service_type")
    last_booking = state_mgr.get_context_value("last_completed_booking", {}) or {}
    used_last_booking = False
    if not service and isinstance(last_booking, dict):
        remembered_service = last_booking.get("service_type")
        if remembered_service:
            service = str(remembered_service)
            used_last_booking = True
    if not service:
        service = extract_service_type(message, clinic_id=clinic_id)
    if service:
        state_mgr.clear_context_key("awaiting_price_service")
        service_key = service.lower()
        reply = service_price_info(service_key, clinic_id=clinic_id)
        if used_last_booking:
            date = str(last_booking.get("date") or "").strip()
            time = str(last_booking.get("time") or "").strip()
            if date and time:
                reply = f"{reply}\n\nImate že termin {date} ob {time}."
        return reply
    state_mgr.set_context_value("awaiting_price_service", True)
    return rag_info_answer(message, info_key_prices, clinic_id=clinic_id)


def handle_info_intent(
    *,
    intent: IntentType,
    message: str,
    clinic_id: str | None,
    decision_service: Optional[str],
    suggested_service: Optional[str],
    appointment_state: dict[str, Any],
    pick_info_key: Callable[[str], Optional[str]],
    get_info_response: Callable[[str, Optional[str]], str],
    rag_info_answer: Callable[[str, str, Optional[str]], str],
    contact_route_words: set[str],
    critical_info_keys: set[str],
    info_keys_direct: set[str],
    info_key_contact: str,
    info_key_location: str,
    info_key_services: str,
) -> Optional[str]:
    if intent != IntentType.INFO:
        return None

    lowered = message.lower()
    asks_location = any(k in lowered for k in ["kje", "naslov", "lokacij", "nahajate", "pridem", "pot"])
    asks_hours = any(k in lowered for k in ["delovni", "delovn", "odprto", "odprti", "kdaj", "ura"])
    if asks_location and asks_hours:
        return (
            f"{get_info_response(info_key_location, clinic_id=clinic_id)}\n\n"
            f"{get_info_response('delovni_cas', clinic_id=clinic_id)}"
        )
    info_key = pick_info_key(message)
    if info_key == "cakalna_doba":
        service = decision_service or suggested_service or appointment_state.get("service_type")
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
    if info_key in critical_info_keys or info_key in info_keys_direct:
        if info_key == info_key_contact and any(k in lowered for k in contact_route_words):
            return get_info_response(info_key_location, clinic_id=clinic_id)
        return get_info_response(info_key, clinic_id=clinic_id)
    if info_key:
        return rag_info_answer(message, info_key, clinic_id=clinic_id)
    return rag_info_answer(message, info_key_services, clinic_id=clinic_id)
