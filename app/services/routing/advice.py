from __future__ import annotations

from typing import Optional

MDT_NO_ADVICE_RESPONSE = (
    "Za zdravstvene nasvete in razlago simptomov se prosimo obrnite na svojega lečečega zdravnika.\n\n"
    "Jaz vam lahko pomagam z informacijami o naših diagnostičnih preiskavah (MR, RTG, UZ) in z naročanjem. "
    "Pokličite nas na 📞 02 23 53 552 ali pišite na ✉️ mr@mdt.si."
)


def generate_health_advice(symptom_description: str) -> str:
    return MDT_NO_ADVICE_RESPONSE


def answer_health_query(message: str, preferred_service: Optional[str] = None) -> str:
    return MDT_NO_ADVICE_RESPONSE


def advice_only(service: Optional[str]) -> str:
    return MDT_NO_ADVICE_RESPONSE


def advice_only_headache() -> str:
    return MDT_NO_ADVICE_RESPONSE
