#!/usr/bin/env python3
"""
Live smoke test for Zdravstveni Center production.
100 chat messages + full admin CRUD.
"""

import requests
import time
import json
import uuid
from datetime import datetime, timedelta

BASE = "https://zdravstvenicenter-production.up.railway.app"
TIMEOUT = 20
DELAY = 0.3

chat_pass = 0
chat_fail = 0
admin_pass = 0
admin_fail = 0

SLOVENIAN_WORDS = [
    "ste", "vas", "je", "na", "in", "se", "za", "pri", "ko", "ali",
    "da", "ne", "mi", "po", "do", "bi", "si", "ga", "jo", "nam",
    "imam", "boli", "prosim", "hvala", "pozdravljeni", "kdaj", "kje",
    "kako", "koliko", "katero", "zdravnik", "pregled", "naročanje",
    "center", "storitve", "delovni", "čas", "telefon", "naslov",
    "cena", "termin", "rezervacija",
]


def get_reply(resp_json):
    return resp_json.get("reply") or resp_json.get("display_text") or ""


def is_slovenian(text):
    text_lower = text.lower()
    return any(w in text_lower for w in SLOVENIAN_WORDS)


def has_no_traceback(text):
    return "Traceback" not in text and "traceback" not in text


def run_chat(session_id, msg, category, idx, checks=None):
    global chat_pass, chat_fail
    label = f"{category} {idx}: \"{msg[:45]}\""
    try:
        r = requests.post(
            f"{BASE}/chat/",
            json={"message": msg, "session_id": session_id},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            print(f"  [FAIL] {label} → HTTP {r.status_code}")
            chat_fail += 1
            return None

        data = r.json()
        reply = get_reply(data)

        if not reply:
            print(f"  [FAIL] {label} → empty reply")
            chat_fail += 1
            return reply

        if not has_no_traceback(reply):
            print(f"  [FAIL] {label} → traceback in response")
            chat_fail += 1
            return reply

        failures = []

        if not is_slovenian(reply):
            failures.append("not Slovenian")

        if checks:
            if "health_advice" in checks:
                terms = ["ni zdravniški", "ni zdravniška", "nasvet", "diagnoza", "posvetujte"]
                if not any(t.lower() in reply.lower() for t in terms):
                    failures.append("missing health disclaimer")

            if "contact" in checks:
                if not any(t in reply for t in ["432", "zc-novak", "Cankar"]):
                    failures.append("missing contact info")

            if "ood" in checks:
                short = len(reply) < 300
                has_phrase = any(t in reply.lower() for t in ["ne morem", "ne razumem", "specifičnih vprašanj"])
                if not (short or has_phrase):
                    failures.append(f"OOD too long ({len(reply)} chars) and no refusal phrase")

        if failures:
            print(f"  [FAIL] {label} → 200, {len(reply)} chars, issues: {', '.join(failures)}")
            chat_fail += 1
        else:
            print(f"  [PASS] {label} → 200, {len(reply)} chars")
            chat_pass += 1

        return reply

    except requests.exceptions.Timeout:
        print(f"  [FAIL] {label} → timeout")
        chat_fail += 1
        return None
    except Exception as e:
        print(f"  [FAIL] {label} → {e}")
        chat_fail += 1
        return None


def run_admin(label, method, path, **kwargs):
    global admin_pass, admin_fail
    url = f"{BASE}/api/admin{path}"
    try:
        r = getattr(requests, method)(url, timeout=TIMEOUT, **kwargs)
        return r
    except requests.exceptions.Timeout:
        print(f"  [FAIL] {method.upper()} {path} → timeout")
        admin_fail += 1
        return None
    except Exception as e:
        print(f"  [FAIL] {method.upper()} {path} → {e}")
        admin_fail += 1
        return None


def check_admin(label, r, path, expected_status=200, check_fn=None):
    global admin_pass, admin_fail
    if r is None:
        return None
    if r.status_code != expected_status:
        print(f"  [FAIL] {label} → HTTP {r.status_code}: {r.text[:200]}")
        admin_fail += 1
        return None
    try:
        data = r.json()
    except Exception:
        data = {}

    if check_fn:
        ok, note = check_fn(data)
        if not ok:
            print(f"  [FAIL] {label} → {note}")
            admin_fail += 1
            return data
        print(f"  [PASS] {label} → {note}")
    else:
        print(f"  [PASS] {label} → HTTP {r.status_code}")

    admin_pass += 1
    return data


# ─────────────────────────────────────────────────────────────
# CHAT TESTS
# ─────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("=== CHAT TESTS ===")
print("=" * 60)

# 1. Lokacija (5)
sid = f"smoke-lokacija-{uuid.uuid4().hex[:8]}"
print("\n[Lokacija]")
for i, msg in enumerate([
    "Kje ste?",
    "Kakšen je vaš naslov?",
    "Kje vas najdem?",
    "Na kateri ulici ste?",
    "Kako pridem do vas?",
], 1):
    run_chat(sid, msg, "Lokacija", i)
    time.sleep(DELAY)

# 2. Kontakt (5)
sid = f"smoke-kontakt-{uuid.uuid4().hex[:8]}"
print("\n[Kontakt]")
for i, msg in enumerate([
    "Kakšna je vaša telefonska?",
    "Na kateri email vas kontaktiram?",
    "Kako vas pokličem?",
    "Dajte mi kontakt",
    "Telefon prosim",
], 1):
    run_chat(sid, msg, "Kontakt", i, checks=["contact"])
    time.sleep(DELAY)

# 3. Delovni čas (5)
sid = f"smoke-delovni-{uuid.uuid4().hex[:8]}"
print("\n[Delovni čas]")
for i, msg in enumerate([
    "Kdaj ste odprti?",
    "Do kdaj delate?",
    "Ali ste odprti v soboto?",
    "Delovni čas prosim",
    "Kdaj zaprete?",
], 1):
    run_chat(sid, msg, "DelovniCas", i)
    time.sleep(DELAY)

# 4. Parkiranje (3)
sid = f"smoke-parking-{uuid.uuid4().hex[:8]}"
print("\n[Parkiranje]")
for i, msg in enumerate([
    "Ali imate parkirišče?",
    "Kje parkiram?",
    "Je parkiranje brezplačno?",
], 1):
    run_chat(sid, msg, "Parkiranje", i)
    time.sleep(DELAY)

# 5. Ekipa/zdravniki (5)
sid = f"smoke-ekipa-{uuid.uuid4().hex[:8]}"
print("\n[Ekipa/zdravniki]")
for i, msg in enumerate([
    "Kdo je direktor?",
    "Kdo so vaši zdravniki?",
    "Ali imate dermatologa?",
    "Kdo je ortoped?",
    "Kakšna je vaša ekipa?",
], 1):
    run_chat(sid, msg, "Ekipa", i)
    time.sleep(DELAY)

# 6. O centru (3)
sid = f"smoke-ocentru-{uuid.uuid4().hex[:8]}"
print("\n[O centru]")
for i, msg in enumerate([
    "Kaj ste?",
    "Povejte mi o vašem centru",
    "Kdaj ste bili ustanovljeni?",
], 1):
    run_chat(sid, msg, "OCentru", i)
    time.sleep(DELAY)

# 7. Storitve - dermatolog (5)
sid = f"smoke-derma-{uuid.uuid4().hex[:8]}"
print("\n[Storitve - dermatolog]")
for i, msg in enumerate([
    "Imate dermatologa?",
    "Kakšne kožne preglede ponujate?",
    "Dermatološki pregled cena?",
    "Imam izpuščaj — h komu?",
    "Zdravite akne?",
], 1):
    run_chat(sid, msg, "Dermatolog", i)
    time.sleep(DELAY)

# 8. Storitve - ortoped (5)
sid = f"smoke-ortoped-{uuid.uuid4().hex[:8]}"
print("\n[Storitve - ortoped]")
for i, msg in enumerate([
    "Imam bolečine v kolenu",
    "Ortopedski pregled?",
    "Boli me hrbet",
    "Ortoped cena?",
    "Imam težave s sklepi",
], 1):
    run_chat(sid, msg, "Ortoped", i)
    time.sleep(DELAY)

# 9. Storitve - okulist (5)
sid = f"smoke-okulist-{uuid.uuid4().hex[:8]}"
print("\n[Storitve - okulist]")
for i, msg in enumerate([
    "Imam slabši vid",
    "Okulistični pregled cena?",
    "Ali pregledujete oči?",
    "Predpišete očala?",
    "Imam suhe oči",
], 1):
    run_chat(sid, msg, "Okulist", i)
    time.sleep(DELAY)

# 10. Storitve - fizioterapija (4)
sid = f"smoke-fizio-{uuid.uuid4().hex[:8]}"
print("\n[Storitve - fizioterapija]")
for i, msg in enumerate([
    "Fizioterapija?",
    "Rehabilitacija po poškodbi?",
    "Masaža hrbta?",
    "Cena fizioterapije?",
], 1):
    run_chat(sid, msg, "Fizioterapija", i)
    time.sleep(DELAY)

# 11. Storitve - laser/estetika (5)
sid = f"smoke-laser-{uuid.uuid4().hex[:8]}"
print("\n[Storitve - laser/estetika]")
for i, msg in enumerate([
    "Laserski poseg žilice?",
    "Botox cena?",
    "Fillerji ustnice?",
    "Estetski posegi?",
    "Bradavice odstranitev?",
], 1):
    run_chat(sid, msg, "Laser", i)
    time.sleep(DELAY)

# 12. Cene (5)
sid = f"smoke-cene-{uuid.uuid4().hex[:8]}"
print("\n[Cene]")
for i, msg in enumerate([
    "Koliko stane dermatolog?",
    "Cena pregleda?",
    "Imate cenik?",
    "Koliko stane ortoped?",
    "Cena okulist?",
], 1):
    run_chat(sid, msg, "Cene", i)
    time.sleep(DELAY)

# 13. Naročanje (5)
sid = f"smoke-narocanje-{uuid.uuid4().hex[:8]}"
print("\n[Naročanje]")
for i, msg in enumerate([
    "Kako se naročim?",
    "Želim rezervirati termin",
    "Postopek naročanja?",
    "Kako rezerviram?",
    "Kdaj imate prosto?",
], 1):
    run_chat(sid, msg, "Narocanje", i)
    time.sleep(DELAY)

# 14. Zdravstveni nasveti (15)
sid = f"smoke-nasveti-{uuid.uuid4().hex[:8]}"
print("\n[Zdravstveni nasveti]")
health_msgs = [
    "Boli me koleno pri hoji - kaj svetujete?",
    "Imam kožni izpuščaj že 3 dni",
    "Boli me hrbet pri sedenju",
    "Imam bolečine v rami pri dvigovanju",
    "Mam rdečino na obrazu",
    "Boli me vrat po spanju",
    "Imam otečeno koleno po teku",
    "Koža mi suha in se lušči",
    "Vidim slabo na daleč",
    "Boli me križ",
    "Imam glivice na nohtih",
    "Po operaciji kolena - kdaj fizioterapija?",
    "Boli me laket pri tipkanju",
    "Imam madež na koži ki raste",
    "Boli me stopalo pri hoji",
]
for i, msg in enumerate(health_msgs, 1):
    run_chat(sid, msg, "Zdravstveni", i, checks=["health_advice"])
    time.sleep(DELAY)

# 15. OOD/nonsense (5)
sid = f"smoke-ood-{uuid.uuid4().hex[:8]}"
print("\n[OOD/nonsense]")
for i, msg in enumerate([
    "42 42 42",
    "bitcoin cena?",
    "Daj mi recept za pogačo",
    "Kolikokrat na dan ješ?",
    "Kak je vreme?",
], 1):
    run_chat(sid, msg, "OOD", i, checks=["ood"])
    time.sleep(DELAY)

# 16. Booking intent (5)
sid = f"smoke-booking-{uuid.uuid4().hex[:8]}"
print("\n[Booking intent]")
for i, msg in enumerate([
    "Naroči me na dermatolog",
    "Rezerviraj mi termin pri ortopedu",
    "Naroči me na pregled",
    "Prihodnji teden bi rad termin",
    "Kdaj ima dr. Kos prosto?",
], 1):
    run_chat(sid, msg, "Booking", i)
    time.sleep(DELAY)

# 17. Urgentno (3)
sid = f"smoke-urgent-{uuid.uuid4().hex[:8]}"
print("\n[Urgentno]")
for i, msg in enumerate([
    "Imam hude prsne bolečine",
    "Težko dišem",
    "Sesedel sem se",
], 1):
    run_chat(sid, msg, "Urgentno", i)
    time.sleep(DELAY)

# 18. Pozdrav/splošno (5)
sid = f"smoke-pozdrav-{uuid.uuid4().hex[:8]}"
print("\n[Pozdrav/splošno]")
for i, msg in enumerate([
    "Pozdravljeni",
    "Hvala za pomoč",
    "Kdo si?",
    "Kaj znaš?",
    "Adijo",
], 1):
    run_chat(sid, msg, "Pozdrav", i)
    time.sleep(DELAY)

# ─────────────────────────────────────────────────────────────
# ADMIN TESTS
# ─────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("=== ADMIN TESTS ===")
print("=" * 60 + "\n")

created_id = None

# 1. GET /reservations
r = run_admin("GET /reservations", "get", "/reservations")
data = check_admin(
    "GET /reservations → list",
    r, "/reservations",
    check_fn=lambda d: (
        ("reservations" in d, f"{len(d.get('reservations', []))} reservations")
        if "reservations" in d else (False, "no 'reservations' key")
    )
)

# 2. GET /reservations?status=pending
r = run_admin("GET /reservations?status=pending", "get", "/reservations", params={"status": "pending"})
check_admin(
    "GET /reservations?status=pending",
    r, "/reservations",
    check_fn=lambda d: (
        ("reservations" in d, f"{len(d.get('reservations', []))} pending")
        if "reservations" in d else (False, "no 'reservations' key")
    )
)

# 3. GET /reservations?type=Ortopedski pregled
r = run_admin("GET /reservations?type=...", "get", "/reservations", params={"type": "Ortopedski pregled"})
check_admin(
    "GET /reservations?type=Ortopedski pregled",
    r, "/reservations",
    check_fn=lambda d: (
        ("reservations" in d, f"{len(d.get('reservations', []))} ortopedski")
        if "reservations" in d else (False, "no 'reservations' key")
    )
)

# 4. POST /reservations — create
# AdminCreateReservation schema requires: date (str), people (int), reservation_type (str)
future_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
test_payload = {
    "date": future_date,
    "people": 1,
    "reservation_type": "Dermatološki pregled",
    "name": "Test Smoke Pacient",
    "email": "test@example.com",
    "phone": "041000111",
    "time": "10:00",
    "note": "Avtomatski smoke test — prosim ignorirajte",
    "source": "admin",
}
r = run_admin("POST /reservations", "post", "/reservations", json=test_payload)
data = check_admin(
    "POST /reservations → create test reservation",
    r, "/reservations",
    check_fn=lambda d: (
        (True, f"id={d.get('id') or d.get('reservation', {}).get('id')}")
        if (d.get("id") or (d.get("reservation") and d["reservation"].get("id"))) else
        (False, f"no id in response: {list(d.keys())}")
    )
)
if data:
    created_id = data.get("id") or (data.get("reservation") or {}).get("id")

print(f"  → Created reservation id: {created_id}")

# 5. GET full list, find by id
if created_id:
    r = run_admin("GET /reservations (find created)", "get", "/reservations")
    data2 = check_admin(
        f"GET /reservations → find id={created_id}",
        r, "/reservations",
        check_fn=lambda d: (
            (
                any(res.get("id") == created_id for res in d.get("reservations", [])),
                f"found id={created_id} in list"
            )
            if "reservations" in d else (False, "no reservations key")
        )
    )
else:
    print("  [SKIP] GET find-by-id: no created_id")

# 6. PUT /reservations/{id}
if created_id:
    put_payload = {
        "name": "Test Smoke Pacient UPDATED",
        "date": (datetime.now() + timedelta(days=8)).strftime("%Y-%m-%d"),
        "time": "11:00",
    }
    r = run_admin(f"PUT /reservations/{created_id}", "put", f"/reservations/{created_id}", json=put_payload)
    check_admin(
        f"PUT /reservations/{created_id} → update name/time",
        r, f"/reservations/{created_id}",
        check_fn=lambda d: (
            (d.get("ok") is True or d.get("success") is True or "reservation" in d or d.get("id") == created_id,
             f"response keys: {list(d.keys())}")
        )
    )
else:
    print("  [SKIP] PUT: no created_id")

# 7. PATCH /reservations/{id}
if created_id:
    r = run_admin(f"PATCH /reservations/{created_id}", "patch", f"/reservations/{created_id}",
                  json={"admin_notes": "Smoke test admin note — ok"})
    check_admin(
        f"PATCH /reservations/{created_id} → admin_notes",
        r, f"/reservations/{created_id}",
        check_fn=lambda d: (
            (d.get("ok") is True or d.get("success") is True or "reservation" in d or d.get("id") == created_id,
             f"response keys: {list(d.keys())}")
        )
    )
else:
    print("  [SKIP] PATCH: no created_id")

# 8. POST /reservations/{id}/confirm
if created_id:
    r = run_admin(f"POST /reservations/{created_id}/confirm", "post", f"/reservations/{created_id}/confirm")
    check_admin(
        f"POST /reservations/{created_id}/confirm",
        r, f"/reservations/{created_id}/confirm",
        check_fn=lambda d: (
            (d.get("success") is True, f"success={d.get('success')}")
        )
    )
else:
    print("  [SKIP] confirm: no created_id")

# 9. GET /reservations/{id}/messages
if created_id:
    r = run_admin(f"GET /reservations/{created_id}/messages", "get", f"/reservations/{created_id}/messages")
    check_admin(
        f"GET /reservations/{created_id}/messages",
        r, f"/reservations/{created_id}/messages",
        check_fn=lambda d: (
            ("messages" in d, f"{len(d.get('messages', []))} messages")
            if "messages" in d else (False, f"keys: {list(d.keys())}")
        )
    )
else:
    print("  [SKIP] messages: no created_id")

# 10. POST /send-message
# SendMessageRequest requires: reservation_id (int), email (str), subject (str), body (str)
send_msg_payload = {
    "reservation_id": created_id if created_id else 1,
    "email": "test@example.com",
    "subject": "Smoke test email",
    "body": "Ta email je del avtomatskega smoke testa. Ignorirajte.",
    "set_processing": False,
}
r = run_admin("POST /send-message", "post", "/send-message", json=send_msg_payload)
check_admin(
    "POST /send-message → test@example.com",
    r, "/send-message",
    check_fn=lambda d: (
        (d.get("ok") is True or d.get("success") is True or "sent" in str(d).lower(),
         f"keys: {list(d.keys())}")
    )
)

# 11. POST /reservations/{id}/reject
if created_id:
    r = run_admin(f"POST /reservations/{created_id}/reject", "post", f"/reservations/{created_id}/reject")
    check_admin(
        f"POST /reservations/{created_id}/reject",
        r, f"/reservations/{created_id}/reject",
        check_fn=lambda d: (
            (d.get("success") is True or "reservation" in d,
             f"keys: {list(d.keys())}")
        )
    )
else:
    print("  [SKIP] reject: no created_id")

# 12. DELETE /reservations/{id}
if created_id:
    r = run_admin(f"DELETE /reservations/{created_id}", "delete", f"/reservations/{created_id}")
    check_admin(
        f"DELETE /reservations/{created_id}",
        r, f"/reservations/{created_id}",
        check_fn=lambda d: (
            (d.get("ok") is True or d.get("success") is True or "deleted" in str(d).lower(),
             f"keys: {list(d.keys())}")
        )
    )
else:
    print("  [SKIP] DELETE: no created_id")

# 13. GET /conversations
r = run_admin("GET /conversations", "get", "/conversations")
check_admin(
    "GET /conversations",
    r, "/conversations",
    check_fn=lambda d: (
        ("conversations" in d, f"{len(d.get('conversations', []))} conversations")
        if "conversations" in d else (False, f"keys: {list(d.keys())}")
    )
)

# 14. GET /usage_stats
r = run_admin("GET /usage_stats", "get", "/usage_stats")
check_admin(
    "GET /usage_stats",
    r, "/usage_stats",
    check_fn=lambda d: (
        (bool(d), f"keys: {list(d.keys())[:6]}")
    )
)

# ─────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────

chat_total = chat_pass + chat_fail
admin_total = admin_pass + admin_fail
total_pass = chat_pass + admin_pass
total = chat_total + admin_total

print("\n" + "=" * 60)
print("=== SUMMARY ===")
print("=" * 60)
print(f"Chat:  {chat_pass}/{chat_total} passed")
print(f"Admin: {admin_pass}/{admin_total} passed")
print(f"Total: {total_pass}/{total} passed")
if total > 0:
    pct = 100 * total_pass / total
    print(f"       ({pct:.1f}%)")
print("=" * 60)
