#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.chat_quality_audit import run_daily_chat_quality_audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Run daily chat quality audit from chat history.")
    parser.add_argument("--days", type=int, default=1, help="How many days back to analyze.")
    parser.add_argument("--max-sessions", type=int, default=2000, help="Maximum sessions to scan.")
    parser.add_argument("--max-examples", type=int, default=20, help="Examples per detected issue.")
    parser.add_argument(
        "--include-test-sessions",
        action="store_true",
        help="Include test/e2e sessions in audit (default: excluded).",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="",
        help="Optional output JSON path. If omitted, prints to stdout.",
    )
    args = parser.parse_args()

    report = run_daily_chat_quality_audit(
        days=args.days,
        max_sessions=args.max_sessions,
        max_examples=args.max_examples,
        exclude_session_prefixes=()
        if args.include_test_sessions
        else (
            "test_center::e2e",
            "test_center::golden",
            "test_center::test",
            "e2e",
            "golden",
            "test-",
        ),
    )

    payload = json.dumps(report, ensure_ascii=False, indent=2)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
        print(f"[audit] report written: {out_path}")
    else:
        print(payload)

    # non-zero exit if issues found (useful for CI/alerting)
    return 1 if int(report.get("issues_total", 0)) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
