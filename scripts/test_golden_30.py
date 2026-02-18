#!/usr/bin/env python3
"""
Golden 30 test suite for unified routing.

Run:
  .venv/bin/python scripts/test_golden_30.py
"""

from __future__ import annotations

from pathlib import Path

from test_framework import TestRunner


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    path = root / "tests" / "golden_30.json"
    rc = TestRunner("GOLDEN 30 - Unified Routing Contract").run_from_json(path)
    print("GOLDEN 30 PASS (100%)" if rc == 0 else "GOLDEN 30 FAIL")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
