"""Info flow helpers for consistent keyword routing."""

from __future__ import annotations


def pick_info_key(message: str, default: str = "kontakt") -> str:
    """Map free-form info question to canonical info response key."""
    lowered = message.lower()

    if any(k in lowered for k in ["lokacija", "naslov", "kje", "nahajate"]):
        return "lokacija"
    if any(k in lowered for k in ["delovni", "ura", "odprt", "kdaj"]):
        return "delovni_cas"
    if any(
        k in lowered
        for k in [
            "parking",
            "parkplac",
            "parkirišče",
            "parkirisce",
            "parkirni",
            "parkirni prostor",
        ]
    ):
        return "parkiranje"
    if any(k in lowered for k in ["kako se naročim", "kako se narocim", "naročanje", "narocanje", "naročim", "narocim"]):
        return "narocanje"
    if any(k in lowered for k in ["telefon", "email", "kontakt"]):
        return "kontakt"

    return default
