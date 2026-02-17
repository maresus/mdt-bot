from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.services.chat_history_service import get_chat_history_service


@dataclass(frozen=True)
class IssueRule:
    code: str
    title: str
    recommendation: str


ISSUE_RULES: dict[str, IssueRule] = {
    "parking_fell_to_generic": IssueRule(
        code="parking_fell_to_generic",
        title="Parking vprašanje je dobilo generičen odgovor",
        recommendation="Dodaj parking/parkirni/mate fraze v info key mapping in fast-pass.",
    ),
    "waiting_time_fell_to_contact": IssueRule(
        code="waiting_time_fell_to_contact",
        title="Čakalna doba je preusmerjena na kontakt",
        recommendation="Dodaj poseben info key za čakalno dobo in odgovor z izborom storitve.",
    ),
    "anti_loop_triggered_on_valid_flow": IssueRule(
        code="anti_loop_triggered_on_valid_flow",
        title="Anti-loop se je sprožil med validnim tokom",
        recommendation="Izključi anti-loop guard med aktivnim booking flow ali dvigni prag.",
    ),
    "uncertain_fallback_returned": IssueRule(
        code="uncertain_fallback_returned",
        title="Vrnjen je bil negotov fallback",
        recommendation="Dodaj intent/routing pravilo za to skupino vprašanj.",
    ),
}


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


def _first_assistant_after(messages: list[dict[str, Any]], start_idx: int) -> dict[str, Any] | None:
    for j in range(start_idx + 1, len(messages)):
        if str(messages[j].get("role", "")).lower() == "assistant":
            return messages[j]
    return None


def run_daily_chat_quality_audit(days: int = 1, max_sessions: int = 2000, max_examples: int = 20) -> dict[str, Any]:
    history = get_chat_history_service()
    since_dt = datetime.now() - timedelta(days=days)
    since = since_dt.isoformat()

    session_ids = history.get_all_sessions(since=since, limit=max_sessions)
    issue_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    issue_counts: dict[str, int] = defaultdict(int)

    sessions_analyzed = 0
    messages_analyzed = 0

    for session_id in session_ids:
        messages = history.get_session_history(session_id=session_id)
        if not messages:
            continue

        # keep only last `days` window for this audit
        filtered: list[dict[str, Any]] = []
        for m in messages:
            ts = str(m.get("timestamp", ""))
            if ts >= since:
                filtered.append(m)

        if not filtered:
            continue

        sessions_analyzed += 1
        messages_analyzed += len(filtered)

        for i, msg in enumerate(filtered):
            if str(msg.get("role", "")).lower() != "user":
                continue

            user_text_raw = str(msg.get("content", ""))
            user_text = _norm(user_text_raw)
            assistant = _first_assistant_after(filtered, i)
            if not assistant:
                continue
            assistant_text_raw = str(assistant.get("content", ""))
            assistant_text = _norm(assistant_text_raw)

            def _add_issue(code: str) -> None:
                issue_counts[code] += 1
                if len(issue_examples[code]) < max_examples:
                    issue_examples[code].append(
                        {
                            "session_id": session_id,
                            "timestamp": str(msg.get("timestamp", "")),
                            "user": user_text_raw,
                            "assistant": assistant_text_raw,
                        }
                    )

            asks_parking = any(k in user_text for k in ("parking", "parkir", "parkirni", "parkplac", "avto"))
            generic_help = "lahko vam pomagam z:" in assistant_text
            if asks_parking and generic_help:
                _add_issue("parking_fell_to_generic")

            asks_waiting = any(k in user_text for k in ("cakam", "cakalna", "koliko cakam", "koliko cakam na"))
            contact_dump = "telefon:" in assistant_text and "email:" in assistant_text
            if asks_waiting and contact_dump:
                _add_issue("waiting_time_fell_to_contact")

            anti_loop = "opazil sem ponavljanje" in assistant_text
            if anti_loop:
                _add_issue("anti_loop_triggered_on_valid_flow")

            uncertain_fallback = "nisem preprican, da pravilno razumem" in assistant_text
            if uncertain_fallback:
                _add_issue("uncertain_fallback_returned")

    issues = []
    for code, count in sorted(issue_counts.items(), key=lambda item: item[1], reverse=True):
        rule = ISSUE_RULES.get(code)
        issues.append(
            {
                "code": code,
                "count": count,
                "title": rule.title if rule else code,
                "recommendation": rule.recommendation if rule else "",
                "examples": issue_examples.get(code, []),
            }
        )

    return {
        "generated_at": datetime.now().isoformat(),
        "period_days": days,
        "period_start": since_dt.isoformat(),
        "sessions_analyzed": sessions_analyzed,
        "messages_analyzed": messages_analyzed,
        "issues_total": sum(issue_counts.values()),
        "issues": issues,
    }

