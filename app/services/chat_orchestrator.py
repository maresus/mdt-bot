from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException

from app.models.chat import ChatRequest, ChatResponse


def process_chat_turn(*, request: ChatRequest, state: dict[str, Any], deps: Any) -> ChatResponse:
    message = request.message.strip()
    raw_session_id = request.session_id or state["chat_session_id"]
    strict_clinic = deps.os.getenv("STRICT_CLINIC_ID", "false").strip().lower() in {"1", "true", "yes", "on"}
    try:
        clinic_id = deps.resolve_clinic_id(request.clinic_id, strict=strict_clinic)
    except ValueError:
        available = deps.list_available_clinics()
        raise HTTPException(status_code=400, detail={"error": "unknown_clinic_id", "available": available})

    token = deps.set_current_clinic_id(clinic_id)
    try:
        session_id = f"{clinic_id}::{raw_session_id}"
        state_mgr = deps.StateManager(session_id)

        if not message:
            payload = deps.format_response(
                deps.get_response("general.empty_message", clinic_id=clinic_id),
                state_manager=state_mgr,
                metadata={"contract_version": "v0.1", "router": "unified_only"},
            )
            return ChatResponse(reply=payload["text"], session_id=raw_session_id, metadata=payload["metadata"])

        now = datetime.now()
        if state["last_interaction"] and (now - state["last_interaction"]).total_seconds() > 3600:
            state["conversation_history"] = []
            if session_id in state["appointment_states"]:
                deps.reset_appointment_state(state["appointment_states"][session_id])
            deps.reset_unified_state(session_id)
        state["last_interaction"] = now

        awaiting_price_service = bool(state_mgr.get_context_value("awaiting_price_service"))
        if awaiting_price_service:
            service_from_message = deps.extract_service_type(message, clinic_id=clinic_id)
            if service_from_message:
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

        fast_pass = deps.get_fast_pass_match(message, clinic_id=clinic_id)
        if fast_pass:
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

        in_booking_flow = deps.is_in_flow(session_id)
        if (not in_booking_flow) and deps.conversation_tracker.detect_loop(session_id, message):
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

        deps.conversation_tracker.add_message(session_id, message)

        response_text = deps.handle_unified_routing(message, session_id, clinic_id=clinic_id)

        if response_text is None and deps.is_in_flow(session_id):
            response_text = deps.handle_appointment_booking(message, session_id)

        if response_text is None:
            cached_response = deps.response_cache.get(message)
            if cached_response:
                response_text = cached_response
            else:
                try:
                    if deps.is_tourist_query(message):
                        response_text = deps.answer_tourist_question(message)
                    else:
                        response_text = deps.answer_with_hybrid_kb(
                            message,
                            history=state["conversation_history"],
                            session_id=session_id,
                            clinic_id=clinic_id,
                        )
                    if len(response_text) > 50 and deps.get_uncertain_marker(clinic_id=clinic_id) not in response_text:
                        deps.response_cache.set(message, response_text)
                except Exception as e:
                    print(f"[UNIFIED_FALLBACK] Error: {e}")
                    response_text = deps.get_response("general.fallback_short", clinic_id=clinic_id)

        state["conversation_history"].append({"role": "user", "content": message})
        state["conversation_history"].append({"role": "assistant", "content": response_text})
        state["last_user_message_by_session"][session_id] = message
        if len(state["conversation_history"]) > 20:
            state["conversation_history"] = state["conversation_history"][-20:]

        decision = deps.unified_route(message, deps.get_unified_state(session_id))
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
            flow_state = deps.get_unified_state(session_id)
            appointment_state = deps.get_appointment_state(session_id)
            current_step = appointment_state.get("step") if appointment_state.get("step") is not None else None
            metadata["flow"] = flow_state.get("flow")
            metadata["booking_step"] = current_step
        except Exception as e:
            print(f"[UI_CONTRACT] Failed to build UI payload: {e}")

        try:
            ap_state = deps.get_appointment_state(session_id)
            current_step = ap_state.get("step") if ap_state.get("step") is not None else None
            deps.save_chat_message(
                session_id=session_id,
                role="user",
                content=message,
                intent=decision.primary_intent.value,
                booking_step=current_step,
                response_cached=False,
            )
            deps.save_chat_message(
                session_id=session_id,
                role="assistant",
                content=response_text,
                booking_step=current_step,
                metadata=metadata,
            )
        except Exception as e:
            print(f"[CHAT_HISTORY] Failed to save conversation: {e}")

        payload = deps.format_response(response_text, state_manager=state_mgr, metadata=metadata)
        if ui_override:
            state_mgr.clear_context_key("ui_override")
        return ChatResponse(reply=payload["text"], session_id=raw_session_id, metadata=payload["metadata"])
    finally:
        deps.reset_current_clinic_id(token)

