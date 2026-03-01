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
    final_must_not_include_any: tuple[str, ...] = ()


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

    def add(kind: str, turns: tuple[str, ...], include_any: tuple[str, ...], exclude_any: tuple[str, ...] = ()) -> None:
        if turns in seen:
            return
        seen.add(turns)
        scenarios.append(Scenario(f"{kind}_{len(scenarios)+1:03d}", turns, include_any, exclude_any))

    openers = ["rad bi termin", "rad bi se narocil", "prosim termin", "narocilo pregleda"]
    services = ["dermatolog", "dermatologo", "ortoped", "ortopet", "okulist", "okulsit"]
    dates = ["17.3.2026", "18.3.2026", "24.3.2026", "26.3.2026", "31.3.2026"]
    times = ["09:00", "10:00", "11:00"]

    info_interrupts = [
        "koliko stane pregled",
        "kontakt",
        "kje ste",
        "parkirni prostor",
        "kaksen delovni cas",
        "a rabim napotnco",
    ]
    confirmations = ["da", "ok", "lahko", "ajde"]

    # 1) booking -> date -> info interrupt -> date/time should continue (220)
    for opener, service, date, intr, time in product(openers, services, dates, info_interrupts, times):
        add(
            "TSW_DATE_INFO_TIME",
            (opener, service, date, intr, time),
            ("ime in priimek", "kako je vase ime", "kako je vaše ime"),
            ("na kateri pregled se zelite narociti", "izberite storitev", "brez ugibanja"),
        )
        if len(scenarios) >= 220:
            break

    # 2) booking -> service -> info/price -> confirm-ish -> date should recover to slot/date flow (160)
    for opener, service, intr, conf, date in product(openers, services, info_interrupts, confirmations, dates):
        add(
            "TSW_CONF_RECOVER",
            (opener, service, intr, conf, date),
            ("prosti termini", "katera ura", "izberite datum", "datum"),
            ("na kateri pregled se zelite narociti", "izberite storitev"),
        )
        if len(scenarios) >= 380:
            break

    # 3) service info -> agree -> topic switch -> return with date/time should still start/continue booking (120)
    service_questions = [
        "imam madez na kozi",
        "neki me pece po kozi",
        "koliko je botox",
        "imam bradavico",
        "zapestje me boli",
    ]
    return_topics = ["kontakt", "parkirni prostor", "kje ste", "koliko stane", "delovni cas"]
    for q, conf, topic, date, time in product(service_questions, confirmations, return_topics, dates, times):
        add(
            "TSW_SERVICEINFO_RETURN",
            (q, conf, topic, date, time),
            ("ime in priimek", "kako je vase ime", "kako je vaše ime", "kateri datum", "katera ura", "prosti termini"),
            ("na kateri pregled se zelite narociti", "izberite storitev"),
        )
        if len(scenarios) >= 500:
            break

    if len(scenarios) < 500:
        raise RuntimeError(f"Expected 500 scenarios, got {len(scenarios)}")
    return scenarios[:500]


SCENARIOS = _build_scenarios()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.scenario_id for s in SCENARIOS])
def test_topic_switch_return_flow_500(client: TestClient, scenario: Scenario) -> None:
    session_id = f"topic-switch-500-{scenario.scenario_id.lower()}"
    replies: list[str] = []

    for message in scenario.turns:
        res = client.post("/chat/", json={"message": message, "session_id": session_id, "clinic_id": "test_center"})
        assert res.status_code == 200
        payload = res.json()
        reply = str(payload.get("reply", "")).strip()
        assert reply
        n = _norm(reply)
        assert "internal server error" not in n
        assert "traceback" not in n
        replies.append(n)

    last = replies[-1]
    assert any(tok in last for tok in scenario.final_must_include_any), (
        f"{scenario.scenario_id} final reply mismatch\nTurns={scenario.turns}\nLast={last}"
    )
    for tok in scenario.final_must_not_include_any:
        assert tok not in last, (
            f"{scenario.scenario_id} final reply derailed\nTurns={scenario.turns}\nLast={last}"
        )


def test_topic_switch_return_flow_500_count() -> None:
    assert len(SCENARIOS) == 500
    assert len({s.turns for s in SCENARIOS}) == 500

