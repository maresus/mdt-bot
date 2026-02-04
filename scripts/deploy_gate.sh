#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$ROOT_DIR/.venv/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
  echo "[DEPLOY GATE] .venv manjka. Ustvari ga in namesti dependencies:"
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

export USE_UNIFIED_ROUTER="${USE_UNIFIED_ROUTER:-true}"

echo "[DEPLOY GATE] Root: $ROOT_DIR"
echo "[DEPLOY GATE] USE_UNIFIED_ROUTER=$USE_UNIFIED_ROUTER"

echo "[1/4] test_golden_30.py"
"$VENV_PY" "$ROOT_DIR/scripts/test_golden_30.py"

echo "[2/4] test_routing.py"
"$VENV_PY" "$ROOT_DIR/scripts/test_routing.py"

echo "[3/4] smoke_test_routing.py"
"$VENV_PY" "$ROOT_DIR/scripts/smoke_test_routing.py"

echo "[4/4] smoke_test_e2e_50.py"
"$VENV_PY" "$ROOT_DIR/scripts/smoke_test_e2e_50.py"

echo "[DEPLOY GATE] OK - Golden30 + routing smoke testi so uspešni."
