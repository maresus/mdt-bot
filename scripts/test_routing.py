#!/usr/bin/env python3
"""Legacy test_routing wrapper (JSON-driven)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.test_framework import TestRunner


def main() -> int:
    suite = PROJECT_ROOT / "tests" / "smoke_routing_40.json"
    return TestRunner("TEST ROUTING").run_from_json(suite)


if __name__ == "__main__":
    raise SystemExit(main())

