#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import uuid
from typing import Iterable

import requests


def _post_chat(base_url: str, clinic_id: str, session_id: str, message: str, endpoint: str) -> str:
    res = requests.post(
        f"{base_url.rstrip('/')}{endpoint}",
        json={"message": message, "session_id": session_id, "clinic_id": clinic_id},
        timeout=30,
    )
    res.raise_for_status()
    data = res.json()
    return str(data.get("reply", ""))


def _run_case(
    base_url: str,
    clinic_id: str,
    endpoint: str,
    name: str,
    turns: list[str],
    expect_any: Iterable[str],
) -> tuple[bool, str]:
    session_id = f"live-smoke::{name}::{uuid.uuid4().hex[:8]}"
    last_reply = ""
    for msg in turns:
        last_reply = _post_chat(base_url, clinic_id, session_id, msg, endpoint).lower()
    passed = any(token.lower() in last_reply for token in expect_any)
    return passed, last_reply


def _detect_endpoint(base_url: str, clinic_id: str) -> str:
    test_msg = "zdravo"
    sid = f"live-smoke-detect::{uuid.uuid4().hex[:8]}"
    for endpoint in ("/chat/", "/v2/chat"):
        try:
            _post_chat(base_url, clinic_id, sid, test_msg, endpoint)
            return endpoint
        except Exception:
            continue
    raise RuntimeError("Nisem našel delujočega chat endpointa (/chat/ ali /v2/chat).")


def main() -> int:
    parser = argparse.ArgumentParser(description="Live smoke tests for production chat API")
    parser.add_argument("--base-url", required=True, help="e.g. https://zdravstvenicenter-production.up.railway.app")
    parser.add_argument("--clinic-id", default="lj_center")
    args = parser.parse_args()
    endpoint = _detect_endpoint(args.base_url, args.clinic_id)

    cases = [
        {
            "name": "booking_flow",
            "turns": ["rad bi se naročil", "dermatolog", "18.3.2026", "08:00"],
            "expect_any": ["kako je vaše ime", "prosim izberite drug termin"],
        },
        {
            "name": "service_typo_and_short_date",
            "turns": ["rad bi se naročil", "dermatologo", "15.3"],
            "expect_any": ["prosti termini", "izberite drug datum"],
        },
        {
            "name": "price_interrupt",
            "turns": ["rad bi se naročil", "okulist", "18.3.2026", "koliko stane pregled", "okulist"],
            "expect_any": ["cena", "30", "120"],
        },
    ]

    summary: list[dict[str, str | bool]] = []
    ok = True
    for case in cases:
        passed, reply = _run_case(
            args.base_url,
            args.clinic_id,
            endpoint,
            case["name"],
            case["turns"],
            case["expect_any"],
        )
        ok = ok and passed
        summary.append({"case": case["name"], "passed": passed, "final_reply": reply[:300]})

    print(json.dumps({"ok": ok, "endpoint": endpoint, "results": summary}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
