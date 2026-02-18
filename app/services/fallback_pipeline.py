from __future__ import annotations

from typing import Any, Optional

from app.models.chat import ChatResponse


def handle_price_followup(
    *,
    message: str,
    raw_session_id: str,
    session_id: str,
    clinic_id: str,
    state_mgr: Any,
    deps: Any,
) -> Optional[ChatResponse]:
    awaiting_price_service = bool(state_mgr.get_context_value("awaiting_price_service"))
    if not awaiting_price_service:
        return None

    service_from_message = deps.extract_service_type(message, clinic_id=clinic_id)
    if not service_from_message:
        return None

    deps.conversation_tracker.add_message(session_id, message)
    state_mgr.clear_context_key("awaiting_price_service")
    response_text = deps.service_price_info(service_from_message, clinic_id=clinic_id)
    if deps.is_in_flow(session_id):
        response_text = deps.build_interrupt_response(
            response_text,
            deps.get_current_step(session_id),
            True,
        )
    payload = deps.format_response(
        response_text,
        state_manager=state_mgr,
        metadata={
            "contract_version": "v0.1",
            "router": "unified_only",
            "price_followup": True,
        },
    )
    return ChatResponse(reply=payload["text"], session_id=raw_session_id, metadata=payload["metadata"])


def handle_fast_pass(
    *,
    message: str,
    raw_session_id: str,
    session_id: str,
    clinic_id: str,
    state_mgr: Any,
    deps: Any,
) -> Optional[ChatResponse]:
    fast_pass = deps.get_fast_pass_match(message, clinic_id=clinic_id)
    if not fast_pass:
        return None

    fast_key = str(fast_pass.get("key") or "")
    if fast_key == deps.INFO_KEY_PRICES and deps.is_in_flow(session_id):
        unified_service = str(deps.get_appointment_data(session_id).get("service_type") or "").strip()
        legacy_service = str(deps.get_appointment_state(session_id).get("service_type") or "").strip()
        suggested_service = str(state_mgr.get_context_value("suggested_service") or "").strip()
        service_for_price = (unified_service or legacy_service or suggested_service).lower()

        if service_for_price:
            deps.conversation_tracker.add_message(session_id, message)
            response_text = deps.service_price_info(service_for_price, clinic_id=clinic_id)
            response_text = deps.build_interrupt_response(
                response_text,
                deps.get_current_step(session_id),
                True,
            )
            payload = deps.format_response(
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

    deps.conversation_tracker.add_message(session_id, message)
    fast_reply = str(fast_pass.get("response", ""))
    if deps.is_in_flow(session_id):
        fast_reply = deps.build_interrupt_response(
            fast_reply,
            deps.get_current_step(session_id),
            True,
        )
    payload = deps.format_response(
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


def handle_loop_guard(
    *,
    message: str,
    raw_session_id: str,
    session_id: str,
    clinic_id: str,
    state_mgr: Any,
    deps: Any,
) -> Optional[ChatResponse]:
    in_booking_flow = deps.is_in_flow(session_id)
    if in_booking_flow or not deps.conversation_tracker.detect_loop(session_id, message):
        return None

    loop_count = deps.conversation_tracker.get_loop_count(session_id)
    deps.conversation_tracker.add_message(session_id, message)
    if deps.looks_like_uncertain_help_request(message):
        payload = deps.format_response(
            deps.default_help_prompt(clinic_id=clinic_id),
            state_manager=state_mgr,
            metadata={"contract_version": "v0.1", "router": "unified_only", "loop_guard": "soft"},
        )
        return ChatResponse(reply=payload["text"], session_id=raw_session_id, metadata=payload["metadata"])
    if loop_count >= 2:
        deps.conversation_tracker.reset_loop_count(session_id)
        payload = deps.format_response(
            deps.get_response("general.anti_loop.apology", clinic_id=clinic_id),
            state_manager=state_mgr,
            metadata={"contract_version": "v0.1", "router": "unified_only", "loop_guard": True},
        )
        return ChatResponse(reply=payload["text"], session_id=raw_session_id, metadata=payload["metadata"])
    payload = deps.format_response(
        deps.get_response("general.anti_loop.warning", clinic_id=clinic_id),
        state_manager=state_mgr,
        metadata={"contract_version": "v0.1", "router": "unified_only", "loop_guard": True},
    )
    return ChatResponse(reply=payload["text"], session_id=raw_session_id, metadata=payload["metadata"])


def resolve_response_fallback(
    *,
    message: str,
    session_id: str,
    clinic_id: str,
    conversation_history: list[dict[str, str]],
    deps: Any,
) -> str:
    cached_response = deps.response_cache.get(message)
    if cached_response:
        return cached_response

    try:
        if deps.is_tourist_query(message):
            response_text = deps.answer_tourist_question(message)
        else:
            response_text = deps.answer_with_hybrid_kb(
                message,
                history=conversation_history,
                session_id=session_id,
                clinic_id=clinic_id,
            )
        if len(response_text) > 50 and deps.get_uncertain_marker(clinic_id=clinic_id) not in response_text:
            deps.response_cache.set(message, response_text)
        return response_text
    except Exception as e:
        print(f"[UNIFIED_FALLBACK] Error: {e}")
        return deps.get_response("general.fallback_short", clinic_id=clinic_id)

