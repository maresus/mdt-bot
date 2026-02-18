#!/usr/bin/env python3
"""Compatibility wrapper for unified scraper (simple mode)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    cmd = [
        sys.executable,
        str(root / "scripts" / "scrape" / "scraper.py"),
        "--mode",
        "simple",
        "--out",
        str(root / "knowledge.jsonl"),
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())

