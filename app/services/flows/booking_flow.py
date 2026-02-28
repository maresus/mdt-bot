"""Booking flow logic extracted from chat_router for modular routing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional, Any


State = dict[str, Optional[str | int | bool]]


@dataclass
class BookingFlowDeps:
    get_appointment_state: Callable[[str], State]
    reset_appointment_state: Callable[[State], None]
    reset_unified_state: Callable[[str], None]
    reset_loop_count: Callable[[str], None]
    set_step: Callable[[str, State, Optional[str]], None]
    set_appointment_field: Callable[[str, State, str, Any], None]
    clear_appointment_data: Callable[[str, State], None]
    is_negative: Callable[[str], bool]
    is_affirmative: Callable[[str], bool]
    is_likely_full_name: Callable[[str], bool]
    extract_service_type: Callable[[str], Optional[str]]
    extract_date_from_message: Callable[[str], Optional[str]]
    extract_time_from_message: Callable[[str], Optional[str]]
    validate_appointment_rules: Callable[..., tuple[bool, str]]
    get_available_time_slots: Callable[[str, str], list[str]]
    get_service_info: Callable[[str], Optional[dict[str, Any]]]
    format_appointment_summary: Callable[[str, str, str, str], str]
    reservation_service_cls: Any
    send_notifications_async: Callable[[dict[str, Any]], None]
    set_context_value: Optional[Callable[[str, str, Any], None]] = None


def get_resume_prompt(state: State, deps: BookingFlowDeps) -> str:
    """Get prompt for current booking step (used when resuming after interrupt)."""
    step = state.get("step")

    if step == "date":
        return "Kateri datum vas zanima? (npr. 15.3.2026)"
    if step == "time":
        return "Katero uro si želite? (npr. 14:00)"
    if step == "name":
        return "Prosim vnesite vaše ime in priimek."
    if step == "phone":
        return "Odlično! Kakšna je vaša telefonska številka?"
    if step == "email":
        return "Kakšen je vaš email naslov? (za potrditev termina)"
    if step == "reason":
        return "Kakšen je razlog vašega obiska? (npr. pregled kožnega znamenja, bolečine v kolenu, ...)"
    if step == "gdpr":
        return """Za obdelavo vašega naročila potrebujemo vaše soglasje:

**Strinjam se z uporabo posredovanih osebnih podatkov za namene naročanja na zdravstvene storitve v skladu z Uredbo GDPR.**

Ali se strinjate? (DA / NE)"""
    if step == "confirm":
        summary = deps.format_appointment_summary(
            str(state.get("date") or ""),
            str(state.get("time") or ""),
            str(state.get("service_type") or ""),
            str(state.get("name") or ""),
        )
        return f"""{summary}

Razlog obiska: {state.get('reason', '-')}
Telefon: {state.get('phone', '-')}
Email: {state.get('email', '-')}

Ali so podatki pravilni? (DA / NE)"""

    return """Na kateri pregled se želite naročiti?

- Dermatološki pregled
- Ortopedski pregled
- Okulistični pregled
- Laserski poseg
- Estetski poseg
- Kozmetični salon"""


def handle_appointment_booking(message: str, session_id: str, deps: BookingFlowDeps) -> str:
    """Handle multi-step appointment booking conversation."""
    state = deps.get_appointment_state(session_id)
    lowered = message.lower()

    if any(word in lowered for word in ["prekliči", "prekini", "ne želim", "nazaj"]):
        deps.clear_appointment_data(session_id, state)
        deps.reset_unified_state(session_id)
        deps.reset_loop_count(session_id)
        return "V redu, rezervacije ne bom nadaljeval. Kaj vas še zanima?"

    if deps.is_negative(message) and state.get("step") != "email":
        deps.clear_appointment_data(session_id, state)
        deps.reset_unified_state(session_id)
        deps.reset_loop_count(session_id)
        return "V redu, naročilo sem preklical. Če želite, lahko začnemo znova."

    # Self-heal flow step if it is missing but partial booking data exists
    # (e.g., after deploy/restart with incomplete legacy state sync).
    if state.get("step") is None:
        has_service = bool(state.get("service_type"))
        has_date = bool(state.get("date"))
        has_time = bool(state.get("time"))
        has_name = bool(state.get("name"))
        has_phone = bool(state.get("phone"))
        has_email = state.get("email") is not None and str(state.get("email")).strip() != ""
        has_reason = bool(state.get("reason"))
        has_gdpr = bool(state.get("gdpr_consent"))

        if has_service and has_date and not has_time:
            deps.set_step(session_id, state, "time")
        elif has_service and has_date and has_time and not has_name:
            deps.set_step(session_id, state, "name")
        elif has_service and has_date and has_time and has_name and not has_phone:
            deps.set_step(session_id, state, "phone")
        elif has_service and has_date and has_time and has_name and has_phone and not has_email and not has_reason:
            deps.set_step(session_id, state, "email")
        elif has_service and has_date and has_time and has_name and has_phone and has_reason and not has_gdpr:
            deps.set_step(session_id, state, "gdpr")
        elif has_service and has_date and has_time and has_name and has_phone and has_reason and has_gdpr:
            deps.set_step(session_id, state, "confirm")
        elif has_service and not has_date:
            deps.set_step(session_id, state, "date")

    # Additional self-heal when step is accidentally reset to "select_service"
    # while booking data already exists (observed after deploy/restart edge cases).
    if state.get("step") == "select_service":
        has_service = bool(state.get("service_type"))
        has_date = bool(state.get("date"))
        has_time = bool(state.get("time"))
        if has_service and has_date and not has_time:
            deps.set_step(session_id, state, "time")
        elif has_service and has_date and has_time:
            deps.set_step(session_id, state, "name")

    if state.get("service_type") is not None and state.get("step") is None:
        date_str = deps.extract_date_from_message(message)
        if date_str:
            deps.set_step(session_id, state, "date")
        else:
            service_info = deps.get_service_info(str(state.get("service_type") or ""))
            if service_info is None:
                deps.set_appointment_field(session_id, state, "service_type", None)
                return """Na kateri pregled se želite naročiti?

- Dermatološki pregled
- Ortopedski pregled
- Okulistični pregled
- Laserski poseg
- Estetski poseg
- Kozmetični salon"""
            deps.set_step(session_id, state, "date")
            return f"""Super!  Naročilo na **{service_info['name']}**.

 Trajanje: {service_info['duration_minutes']} minut
 Cena: {service_info['price_range']}

Kateri datum vas zanima? (npr. 15.3.2026)"""

    if state.get("step") in (None, "select_service") or state.get("service_type") is None:
        service_type = deps.extract_service_type(message)
        if service_type:
            deps.set_appointment_field(session_id, state, "service_type", service_type)
            deps.set_step(session_id, state, "date")
            service_info = deps.get_service_info(service_type)
            return f"""Odlično! Naročilo na **{service_info['name']}**.

Trajanje: {service_info['duration_minutes']} minut
Cena: {service_info['price_range']}

Kateri datum vas zanima? (npr. 15.3.2026)"""
        deps.set_step(session_id, state, "select_service")
        return """Na kateri pregled se želite naročiti?

- Dermatološki pregled
- Ortopedski pregled
- Okulistični pregled
- Laserski poseg
- Estetski poseg
- Kozmetični salon"""

    if state.get("step") == "date" or state.get("date") is None:
        date_str = deps.extract_date_from_message(message)
        if date_str:
            valid, error = deps.validate_appointment_rules(
                date_str=date_str,
                time_str="10:00",
                service_type=str(state.get("service_type") or ""),
                patient_name="",
                patient_phone="",
            )

            if not valid and "datum" in error.lower():
                return f" {error}\n\nProsim izberite drug datum."

            deps.set_appointment_field(session_id, state, "date", date_str)
            deps.set_step(session_id, state, "time")

            slots = deps.get_available_time_slots(date_str, str(state.get("service_type") or ""))
            if not slots:
                return f"""Žal za {date_str} ni prostih terminov.

Prosim izberite drug datum."""

            slots_str = ", ".join(slots[:10])
            if len(slots) > 10:
                slots_str += f" ... (še {len(slots) - 10} terminov)"

            return f"""Prosti termini za {date_str}:

{slots_str}

Katera ura vam ustreza?"""

        return "Kateri datum vas zanima? (Prosim v formatu DD.MM.YYYY, npr. 15.03.2026)"

    if state.get("step") == "time" or state.get("time") is None:
        time_str = deps.extract_time_from_message(message)
        if time_str:
            valid, error = deps.validate_appointment_rules(
                date_str=str(state.get("date") or ""),
                time_str=time_str,
                service_type=str(state.get("service_type") or ""),
                patient_name="",
                patient_phone="",
            )

            if not valid:
                return f" {error}\n\nProsim izberite drug termin."

            deps.set_appointment_field(session_id, state, "time", time_str)
            deps.set_step(session_id, state, "name")
            return f"""Termin {state['date']} ob {time_str} je prost! 

Kako je vaše ime in priimek?"""

        return "Prosim povejte uro termina (npr. 10:00 ali ob 10)"

    if state.get("step") == "name" or state.get("name") is None:
        if deps.is_likely_full_name(message):
            deps.set_appointment_field(session_id, state, "name", message.strip())
            deps.set_step(session_id, state, "phone")
            return "Hvala! Kakšna je vaša telefonska številka?"
        return "Prosim vnesite vaše ime in priimek."

    if state.get("step") == "phone" or state.get("phone") is None:
        phone = re.sub(r"[^\d+]", "", message)
        if len(phone) >= 8:
            deps.set_appointment_field(session_id, state, "phone", phone)
            deps.set_step(session_id, state, "email")
            return "Odlično! Kakšen je vaš email naslov? (za potrditev termina)"
        return "Prosim vnesite veljavno telefonsko številko."

    if state.get("step") == "email" or state.get("email") is None:
        if deps.is_negative(message):
            deps.set_appointment_field(session_id, state, "email", None)
            deps.set_step(session_id, state, "reason")
            return "V redu, brez e-pošte. Kakšen je razlog vašega obiska? (npr. pregled kožnega znamenja, bolečine v kolenu, ...)"
        if "@" in message and "." in message.split("@")[1]:
            deps.set_appointment_field(session_id, state, "email", message.strip())
            deps.set_step(session_id, state, "reason")
            return "Kakšen je razlog vašega obiska? (npr. pregled kožnega znamenja, bolečine v kolenu, ...)"
        return "Prosim vnesite veljaven email naslov."

    if state.get("step") == "reason" or state.get("reason") is None:
        deps.set_appointment_field(session_id, state, "reason", message.strip())
        deps.set_step(session_id, state, "gdpr")

        return """Za obdelavo vašega naročila potrebujemo vaše soglasje:

**Strinjam se z uporabo posredovanih osebnih podatkov za namene naročanja na zdravstvene storitve v skladu z Uredbo GDPR.**

Ali se strinjate? (DA / NE)"""

    if state.get("step") == "gdpr":
        if deps.is_affirmative(message):
            from datetime import datetime
            deps.set_appointment_field(session_id, state, "gdpr_consent", datetime.now().isoformat())
            deps.set_step(session_id, state, "confirm")

            summary = deps.format_appointment_summary(
                str(state.get("date") or ""),
                str(state.get("time") or ""),
                str(state.get("service_type") or ""),
                str(state.get("name") or ""),
            )

            email_display = state.get("email") or "-"
            return f"""{summary}

Razlog obiska: {state['reason']}
Telefon: {state['phone']}
Email: {email_display}

Ali so podatki pravilni? (DA / NE)"""
        if deps.is_negative(message):
            deps.clear_appointment_data(session_id, state)
            deps.reset_unified_state(session_id)
            return "Brez soglasja GDPR žal ne moremo nadaljevati z naročilom. Če imate vprašanja, nas kontaktirajte po telefonu."
        return "Prosim odgovorite z DA ali NE."

    if state.get("step") == "confirm":
        if deps.is_affirmative(message):
            try:
                rs = deps.reservation_service_cls()
                service_info = deps.get_service_info(str(state.get("service_type") or ""))

                res_id = rs.create_reservation(
                    date=state["date"],
                    people=1,
                    reservation_type="table",
                    time=state["time"],
                    location=service_info["name"],
                    service_type=str(state["service_type"]).upper(),
                    duration_minutes=service_info["duration_minutes"],
                    name=state["name"],
                    phone=state["phone"],
                    email=state["email"],
                    reason=state["reason"],
                    gdpr_consent=state.get("gdpr_consent"),
                    source="chat",
                )

                appointment_data = {
                    "id": res_id,
                    "name": state["name"],
                    "email": state["email"],
                    "phone": state["phone"],
                    "date": state["date"],
                    "time": state["time"],
                    "location": service_info["name"],
                    "service_type": state["service_type"],
                    "service_name": service_info["name"],
                    "duration_minutes": service_info["duration_minutes"],
                    "reason": state["reason"],
                    "reservation_type": "table",
                }
                deps.send_notifications_async(appointment_data)

                email = state.get("email")
                date = state["date"]
                time = state["time"]
                service_type = state.get("service_type")
                service_name = service_info["name"]

                deps.reset_appointment_state(state)
                deps.reset_unified_state(session_id)
                if deps.set_context_value:
                    deps.set_context_value(
                        session_id,
                        "last_completed_booking",
                        {
                            "id": res_id,
                            "service_type": service_type,
                            "service_name": service_name,
                            "date": date,
                            "time": time,
                        },
                    )

                email_line = (
                    f"Potrditev smo poslali na {email}."
                    if email
                    else "Potrditev po e-pošti ni bila zahtevana."
                )
                return f""" **Naročilo uspešno ustvarjeno!**

Številka naročila: #{res_id}

{email_line}
Vidimo se {date} ob {time}!

Če imate še kakšna vprašanja, mi jih lahko zastavite."""

            except Exception as e:
                print(f"[BOOKING] Error creating appointment: {e}")
                return f""" Prišlo je do napake pri ustvarjanju naročila.

Prosim kontaktirajte nas na [telefonska številka] ali [email].

Napaka: {str(e)}"""

        if any(word in lowered for word in ["ne", "no", "popravi"]):
            deps.clear_appointment_data(session_id, state)
            deps.reset_unified_state(session_id)
            return "Podatki razveljavljeni. Začnimo znova - na kateri pregled se želite naročiti?"

        return "Prosim odgovorite z DA ali NE."

    return "Oprostite, nisem razumel. Lahko ponovite?"
