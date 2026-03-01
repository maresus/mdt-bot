from __future__ import annotations

from typing import Optional


WAITING_TIME_MARKERS = (
    "cakam",
    "čakam",
    "cakalna",
    "čakalna",
    "koliko cakam",
    "koliko čakam",
    "kolk cakam",
    "kak dolgo cakam",
    "kak dolgo čak",
    "dolgo cakam",
)

SERVICE_PROVIDER_MARKERS = (
    "kdo opravlja",
    "kdo dela",
    "kdo izvaja",
    "kdo pregleda",
    "kdo je specialist",
    "kateri zdravnik",
    "katera zdravnica",
)

QUESTION_MARKERS = ("?", "kdo", "kateri", "katera", "katere", "ali")

BOOKING_PUSH_MARKERS = (
    "naroc",
    "naroč",
    "termin",
    "rezerv",
    "book",
    "vrzi",
    "vrži",
)

SERVICE_ROLE_LABELS = {
    "dermatolog": "dermatolog",
    "ortoped": "ortoped",
    "okulist": "okulist",
    "laserski_poseg": "specialist za laserske posege",
    "estetski_poseg": "specialist za estetske posege",
    "fizioterapija": "fizioterapevt",
    "kozmetika": "kozmetični strokovnjak",
}


def looks_like_waiting_time_question(message: str) -> bool:
    lowered = (message or "").lower()
    return any(marker in lowered for marker in WAITING_TIME_MARKERS)


def looks_like_service_provider_question(message: str) -> bool:
    lowered = (message or "").lower()
    if not any(marker in lowered for marker in QUESTION_MARKERS):
        return False
    return any(marker in lowered for marker in SERVICE_PROVIDER_MARKERS)


def looks_like_booking_push_message(message: str) -> bool:
    lowered = (message or "").lower()
    return any(marker in lowered for marker in BOOKING_PUSH_MARKERS)


def build_waiting_time_reply(service_type: Optional[str]) -> str:
    if service_type:
        service_label = str(service_type).lower().replace("_", " ")
        return (
            "Čakalna doba je odvisna od storitve in termina. "
            f"Za {service_label} lahko takoj preverim prvi prost termin."
        )
    return (
        "Čakalna doba je odvisna od storitve. "
        "Napišite prosim kateri pregled želite (npr. dermatolog, ortoped, okulist), "
        "pa preverim prvi prost termin."
    )


def build_service_provider_reply(
    *,
    service_type: str,
    service_name: str,
    duration_minutes: int | None,
    price_range: str | None,
) -> str:
    role = SERVICE_ROLE_LABELS.get(service_type.lower(), "specialist")
    parts = [
        f"{service_name} opravlja {role}.",
    ]
    if duration_minutes:
        parts.append(f"Trajanje pregleda: {duration_minutes} minut.")
    if price_range:
        parts.append(f"Cena: {price_range}.")
    parts.append("Če želite, lahko takoj preverim prvi prost termin.")
    return "\n".join(parts)

