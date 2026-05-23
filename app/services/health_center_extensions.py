"""
MDT&T - Razširitve za rezervacije pregledov

Storitve:
- Dermatološki pregledi
- Ortopedski pregledi
- Okulistični pregledi
- Laserski posegi
- Estetski posegi
- Kozmetični salon
"""
from datetime import datetime, timedelta
import os
from typing import Optional, Tuple, List, Set, Dict, Any

# Variacije imen storitev za prepoznavo v besedilu.
SERVICE_NAME_MAP = {
    "dermatolog": [
        "dermatolog", "dermatološki", "koža", "kozni", "kožne",
        "dermatovenerolog", "dermatovenerološki",
        "dermatalog", "dermatalogu", "dermatlog",
        "znamenje", "znamnje",
        "skin", "rash", "mole", "acne",
    ],
    "ortoped": ["ortoped", "ortopedski", "ortopedija", "koleno", "hrbtenica", "knee", "back", "shoulder", "joint"],
    "okulist": ["okulist", "okulistični", "oči", "očesni", "ocena vida", "oftalmolog", "eye", "eyes", "vision", "eye check", "eye exam"],
    "laserski_poseg": ["laser", "laserski", "žile", "žilice", "bradavice", "glivice", "mozolj", "mozolji"],
    "estetski_poseg": ["estetski", "botox", "botulinum", "filer", "filerji", "polnila", "radiofrekvenca", "prx"],
    "kozmetika": ["kozmetika", "kozmetični", "nega obraza", "dermavita", "pedikura", "facial", "cosmetic"],
}

# Tipi storitev in njihova trajanja (v minutah)
SERVICES = {
    "dermatolog": {
        "name": "Dermatološki pregled",
        "duration_minutes": 30,
        "price_range": "25-150 €",
        "description": "Pregledi kožnih bolezni, laserski in estetski posegi"
    },
    "ortoped": {
        "name": "Ortopedski pregled",
        "duration_minutes": 30,
        "price_range": "40-80 €",
        "description": "Pregledi sklepov, hrbtenice, športne poškodbe"
    },
    "okulist": {
        "name": "Okulistični pregled",
        "duration_minutes": 30,
        "price_range": "30-120 €",
        "description": "Očesni pregledi, predpis očal in leč"
    },
    "laserski_poseg": {
        "name": "Laserski poseg",
        "duration_minutes": 30,
        "price_range": "50-200 €",
        "description": "Lasersko odstranjevanje žilic, bradavic, zdravljenje glivic"
    },
    "estetski_poseg": {
        "name": "Estetski poseg",
        "duration_minutes": 30,
        "price_range": "100-400 €",
        "description": "Botox, fillerji, biorevitalizacija, radiofrekvenca"
    },
    "kozmetika": {
        "name": "Kozmetični salon",
        "duration_minutes": 60,
        "price_range": "30-100 €",
        "description": "Nega obraza, tretmaji kože"
    },
}

try:
    from app.services.clinic_config import get_clinic_config
except Exception:  # pragma: no cover - safe fallback for legacy imports
    get_clinic_config = None

# Delovni čas MDT&T
WORKING_HOURS = {
    "start": 8,  # 8:00
    "end": 20,   # 20:00 (zadnji termin ob 19:30)
}

# Dni v tednu (0=ponedeljek, 6=nedelja) — MDT&T je odprt vsak dan
WORKING_DAYS = {0, 1, 2, 3, 4, 5, 6}


def get_services(clinic_id: Optional[str] = None) -> Dict[str, Any]:
    if get_clinic_config is None:
        return SERVICES
    config = get_clinic_config(
        clinic_id=clinic_id,
        defaults={"services": SERVICES, "service_map": SERVICE_NAME_MAP},
    )
    services = config.get("services") if isinstance(config, dict) else None
    return services if isinstance(services, dict) else SERVICES


def get_service_map(clinic_id: Optional[str] = None) -> Dict[str, List[str]]:
    if get_clinic_config is None:
        return SERVICE_NAME_MAP
    config = get_clinic_config(
        clinic_id=clinic_id,
        defaults={"services": SERVICES, "service_map": SERVICE_NAME_MAP},
    )
    service_map = config.get("service_map") if isinstance(config, dict) else None
    return service_map if isinstance(service_map, dict) else SERVICE_NAME_MAP


def _get_booked_slots(date_str: str) -> Set[str]:
    """
    Vrne set zasedenih terminov za izbran dan iz baze.

    Args:
        date_str: Datum v formatu DD.MM.YYYY

    Returns:
        Set terminov ki so že zasedeni (npr. {"08:00", "10:30"})
    """
    try:
        # Lazy import to avoid circular dependency
        from app.services.reservation_service import ReservationService

        service = ReservationService()
        booked_times: Set[str] = set()

        # Check all active reservation statuses
        for status in ["pending", "confirmed", "processing"]:
            existing = service.read_reservations(
                reservation_type="table",
                status=status,
                limit=1000
            )
            for r in existing:
                if r.get("date") == date_str:
                    time_slot = r.get("time")
                    if time_slot:
                        # Normalize time format (ensure HH:MM)
                        if ":" in time_slot:
                            parts = time_slot.split(":")
                            normalized = f"{int(parts[0]):02d}:{int(parts[1]):02d}"
                            booked_times.add(normalized)

        return booked_times

    except Exception as e:
        print(f"[SLOTS] Error getting booked slots: {e}")
        return set()  # Return empty set on error (show all slots)


def get_available_time_slots(date_str: str, service_type: str, clinic_id: Optional[str] = None) -> List[str]:
    """
    Vrne seznam prostih terminov za izbran dan in storitev.

    SEDAJ PREVERJA DATABASE za že zasedene termine!

    Args:
        date_str: Datum v formatu DD.MM.YYYY
        service_type: Tip storitve (ključ iz SERVICES)

    Returns:
        Seznam PROSTIH terminov v formatu ["08:00", "08:30", "09:00", ...]
    """
    try:
        date = datetime.strptime(date_str.strip(), "%d.%m.%Y")
    except ValueError:
        return []

    # Check if working day
    if date.weekday() not in WORKING_DAYS:
        return []

    services = get_services(clinic_id)

    # Get service duration
    if service_type not in services:
        return []

    duration = services[service_type]["duration_minutes"]

    # Get already booked slots from database
    booked_slots = _get_booked_slots(date_str)

    if booked_slots:
        print(f"[SLOTS] Found {len(booked_slots)} booked slots for {date_str}: {booked_slots}")

    # Generate time slots
    slots = []
    current_hour = WORKING_HOURS["start"]
    current_minute = 0

    while True:
        # Check if slot + duration fits within working hours
        end_hour = current_hour + (current_minute + duration) // 60
        end_minute = (current_minute + duration) % 60

        if end_hour > WORKING_HOURS["end"] or (end_hour == WORKING_HOURS["end"] and end_minute > 0):
            break

        time_str = f"{current_hour:02d}:{current_minute:02d}"

        # Only add slot if NOT already booked
        if time_str not in booked_slots:
            slots.append(time_str)

        # Next slot (30 min interval)
        current_minute += 30
        if current_minute >= 60:
            current_hour += 1
            current_minute = 0

    return slots


def validate_appointment_rules(
    date_str: str,
    time_str: str,
    service_type: str,
    patient_name: Optional[str] = None,
    patient_phone: Optional[str] = None,
    clinic_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Validira pravila za rezervacijo termina.

    Args:
        date_str: Datum v formatu DD.MM.YYYY
        time_str: Čas v formatu HH:MM
        service_type: Tip storitve (dermatolog, ortoped, okulist, ...)
        patient_name: Ime pacienta (opcijsko)
        patient_phone: Telefon pacienta (opcijsko)

    Returns:
        (is_valid, error_message)
    """
    # Parse date
    try:
        appointment_date = datetime.strptime(date_str.strip(), "%d.%m.%Y")
    except ValueError:
        return False, "Datum prosimo v obliki DD.MM.YYYY (npr. 15.3.2025)."

    # Check if date is in future
    today = datetime.now().date()
    if appointment_date.date() < today:
        today_str = today.strftime("%d.%m.%Y")
        return False, f"Ta datum je že mimo (danes je {today_str}). Prosimo izberite datum v prihodnosti."

    # Check if too far in future (max 90 days)
    max_future = today + timedelta(days=90)
    if appointment_date.date() > max_future:
        return False, "Termine lahko naročate največ 90 dni vnaprej. Prosimo izberite bližji datum."

    # Check working day
    weekday = appointment_date.weekday()
    if weekday not in WORKING_DAYS:
        return False, "MDT&T je odprt vsak dan. Prosimo izberite drug datum."

    # Check service type
    services = get_services(clinic_id)
    if service_type not in services:
        available = ", ".join([s["name"] for s in services.values()])
        return False, f"Neveljaven tip storitve. Na voljo: {available}"

    # Parse time
    try:
        hour = int(time_str.split(":")[0])
        minute = int(time_str.split(":")[1]) if ":" in time_str else 0
    except (ValueError, IndexError):
        return False, "Uro prosimo v obliki HH:MM (npr. 14:00)."

    # Check if time is within working hours
    if hour < WORKING_HOURS["start"] or hour >= WORKING_HOURS["end"]:
        return False, f"Delovni čas je od {WORKING_HOURS['start']}:00 do {WORKING_HOURS['end']}:00."

    # Check if minute is valid (only :00 or :30)
    if minute not in [0, 30]:
        return False, "Termini so na voljo ob polni in pol uri (npr. 9:00, 9:30, 10:00, ...)."

    # Check if appointment fits before closing
    duration = services[service_type]["duration_minutes"]
    end_hour = hour + (minute + duration) // 60
    end_minute = (minute + duration) % 60

    if end_hour > WORKING_HOURS["end"] or (end_hour == WORKING_HOURS["end"] and end_minute > 0):
        last_slot_hour = WORKING_HOURS["end"] - 1
        last_slot_minute = 30 if duration <= 30 else 0
        return False, f"Ta termin bi trajal čez delovni čas. Zadnji možni termin je ob {last_slot_hour}:{last_slot_minute:02d}."

    return True, ""


def format_appointment_summary(
    date: str,
    time: str,
    service_type: str,
    patient_name: Optional[str] = None,
    clinic_id: Optional[str] = None,
) -> str:
    """
    Formatira povzetek rezervacije termina za prikaz uporabniku.
    """
    services = get_services(clinic_id)
    service = services.get(service_type, {"name": service_type, "duration_minutes": 30, "price_range": "Na voljo ob potrditvi"})

    patient_info = f"\n Pacient: {patient_name}" if patient_name else ""

    return f"""
 **MDT&T - Rezervacija termina**

 Datum: {date}
 Čas: {time}
⏱ Trajanje: {service["duration_minutes"]} minut
 Storitev: {service["name"]}
 Cena: {service["price_range"]}{patient_info}

 Lokacija: [Naslov zdravstvenega centra]
 Kontakt: [Telefonska številka]

**Navodila:**
- Prosimo pridite 10 minut pred terminom
- S seboj prinesite zdravstveno izkaznico (če jo imate)
- V primeru preprečitve nas prosimo obvestite vsaj 24 ur vnaprej
""".strip()


def get_service_info(service_type: str, clinic_id: Optional[str] = None) -> Optional[dict]:
    """
    Vrne informacije o storitvi.

    Returns:
        {"name": str, "duration_minutes": int, "price_range": str, "description": str} or None
    """
    services = get_services(clinic_id)
    return services.get(service_type)


def format_all_services_summary(clinic_id: Optional[str] = None) -> str:
    """
    Formatira seznam vseh razpoložljivih storitev.
    """
    lines = [" **MDT&T - Storitve**\n"]

    services = get_services(clinic_id)
    for service_type, info in services.items():
        lines.append(f"**{info['name']}**")
        lines.append(f"⏱ Trajanje: {info['duration_minutes']} min")
        lines.append(f" Cena: {info['price_range']}")
        lines.append(f"{info['description']}\n")

    lines.append(" Lokacija: [Naslov zdravstvenega centra]")
    lines.append(" Kontakt: [Telefonska številka]")
    lines.append(" Delovni čas: Pon-Pet 8:00-18:00")

    return "\n".join(lines)
