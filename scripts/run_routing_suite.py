#!/usr/bin/env python3
"""Run any routing suite JSON with the shared test framework."""

from __future__ import annotations

import argparse
from pathlib import Path

from test_framework import TestRunner


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", required=True, help="Path to suite JSON file")
    parser.add_argument("--name", default="Routing Suite", help="Suite display name")
    args = parser.parse_args()

    path = Path(args.suite).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path

    return TestRunner(args.name).run_from_json(path)


if __name__ == "__main__":
    raise SystemExit(main())
