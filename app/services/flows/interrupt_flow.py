"""Soft-interrupt resolution extracted from chat_router."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from app.services.routing.unified_router import IntentType
from .info_flow import pick_info_key


@dataclass
class InterruptFlowDeps:
    get_info_response: Callable[[str], str]
    service_price_info: Callable[[Optional[str]], str]
    get_service_info: Callable[[str], Optional[dict[str, Any]]]


def resolve_interrupt_answer(
    *,
    message: str,
    primary_intent: IntentType,
    service_hint: str | None,
    active_service: str | None,
    deps: InterruptFlowDeps,
) -> str | None:
    """Resolve answer text for soft interrupt during active booking flow."""
    if primary_intent == IntentType.INFO:
        return deps.get_info_response(pick_info_key(message))

    if primary_intent == IntentType.PRICE:
        service_key = active_service or service_hint
        return deps.service_price_info(service_key.lower() if service_key else None)

    if primary_intent == IntentType.SERVICE_INFO:
        if service_hint:
            service_info = deps.get_service_info(str(service_hint).lower())
            if service_info:
                return (
                    f"Za to je najprimernejši **{service_info['name']}** "
                    f"({service_info['duration_minutes']} min, {service_info['price_range']})."
                )
        return deps.get_info_response("storitve")

    return None
