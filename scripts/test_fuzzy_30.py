#!/usr/bin/env python3
"""
Fuzzy 30 test suite for unified routing (variant phrases).
"""

from __future__ import annotations

from pathlib import Path

from scripts.test_framework import TestRunner


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    path = root / "tests" / "fuzzy_30.json"
    rc = TestRunner("FUZZY 30 - Unified Routing Variants").run_from_json(path)
    print("FUZZY 30 PASS (100%)" if rc == 0 else "FUZZY 30 FAIL")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
