from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.chat_router import router as chat_router


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    turns: tuple[str, ...]
    final_must_include_any: tuple[str, ...]
    final_must_not_include: tuple[str, ...] = ()


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(chat_router)
    return TestClient(app)


def _norm(text: str) -> str:
    return (
        (text or "")
        .lower()
        .replace("š", "s")
        .replace("č", "c")
        .replace("ž", "z")
        .replace("ć", "c")
        .replace("đ", "d")
    )


def _build_scenarios() -> list[Scenario]:
    scenarios: list[Scenario] = []
    seen: set[tuple[str, ...]] = set()

    def add(kind: str, turns: tuple[str, ...], include_any: tuple[str, ...], must_not: tuple[str, ...] = ()) -> None:
        if turns in seen:
            return
        seen.add(turns)
        scenarios.append(Scenario(f"{kind}_{len(scenarios)+1:03d}", turns, include_any, must_not))

    # Stable dates/times used across tests to avoid weekend/invalid noise.
    dates = ["17.3.2026", "18.3.2026", "24.3.2026", "26.3.2026", "31.3.2026"]
    times = ["09:00", "10:00", "11:00"]
    booking_openers = ["rad bi se narocil", "rad bi termin", "narocilo pregleda", "prosim termin", "lahko termin"]
    services = ["dermatolog", "dermatologo", "ortoped", "ortopet", "okulist", "okulsit"]

    # 1) Core booking continuity: after date+time final reply should ask for name, not reset to service list (250)
    for opener, service, date, time in product(booking_openers, services, dates, times):
        add(
            "FLOW_CORE",
            (opener, service, date, time),
            ("ime in priimek", "kako je vase ime", "kako je vaše ime"),
            ("na kateri pregled se zelite narociti", "izberite storitev"),
        )
        if len(scenarios) >= 250:
            break

    # 2) Flow with info interruptions before date/time should still continue (150)
    interruptions = ["kontakt", "kje ste", "koliko stane pregled", "parkirni prostor", "delovni cas"]
    for opener, service, intr, date, time in product(booking_openers, services, interruptions, dates, times):
        # date after interruption
        add(
            "FLOW_INTR_DATE",
            (opener, service, intr, date),
            ("prosti termini", "katera ura", "izberite datum", "datum"),
        )
        # time after interruption post-slots
        add(
            "FLOW_INTR_TIME",
            (opener, service, date, intr, time),
            ("ime in priimek", "kako je vase ime", "kako je vaše ime"),
            ("na kateri pregled se zelite narociti", "izberite storitev"),
        )
        if len(scenarios) >= 400:
            break

    # 3) One-line booking + follow-up time should continue to name step (100)
    one_line_templates = [
        "rad bi termin pri {service} {date} ob {time_hint}",
        "prosim {service} pregled {date} ob {time_hint}",
        "narocite me za {service} {date} ob {time_hint}",
        "lahko termin {service} {date} ob {time_hint}",
        "book me {service} {date} {time_hint}",
    ]
    # Some bots still list slots after one-line request; sending exact time next should move to name.
    for tpl, service, date, time in product(one_line_templates, services, dates, times):
        hinted = "9" if time == "09:00" else time
        first = tpl.format(service=service, date=date, time_hint=hinted)
        add(
            "FLOW_ONELINE",
            (first, time),
            ("ime in priimek", "kako je vase ime", "kako je vaše ime"),
            ("na kateri pregled se zelite narociti", "izberite storitev"),
        )
        if len(scenarios) >= 500:
            break

    if len(scenarios) < 500:
        raise RuntimeError(f"Expected 500 scenarios, got {len(scenarios)}")
    return scenarios[:500]


SCENARIOS = _build_scenarios()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.scenario_id for s in SCENARIOS])
def test_flow_aware_regressions_500(client: TestClient, scenario: Scenario) -> None:
    session_id = f"flow-aware-500-{scenario.scenario_id.lower()}"
    replies: list[str] = []

    for message in scenario.turns:
        res = client.post(
            "/chat/",
            json={"message": message, "session_id": session_id, "clinic_id": "test_center"},
        )
        assert res.status_code == 200
        payload = res.json()
        reply = str(payload.get("reply", "")).strip()
        assert reply
        norm = _norm(reply)
        assert "internal server error" not in norm
        assert "traceback" not in norm
        replies.append(norm)

    last = replies[-1]
    assert any(token in last for token in scenario.final_must_include_any), (
        f"{scenario.scenario_id} final reply mismatch.\nTurns={scenario.turns}\nLast={last}"
    )
    for token in scenario.final_must_not_include:
        assert token not in last, (
            f"{scenario.scenario_id} unexpectedly reset/derailed.\nTurns={scenario.turns}\nLast={last}"
        )


def test_flow_aware_regressions_500_count() -> None:
    assert len(SCENARIOS) == 500
    assert len({s.turns for s in SCENARIOS}) == 500

