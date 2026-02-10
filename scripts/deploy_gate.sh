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

echo "[1/9] test_d3_modules.py"
"$VENV_PY" "$ROOT_DIR/scripts/test_d3_modules.py"

echo "[2/9] test_golden_30.py"
"$VENV_PY" "$ROOT_DIR/scripts/test_golden_30.py"

echo "[3/9] test_golden_runner.py"
"$VENV_PY" -m pytest "$ROOT_DIR/tests/test_golden_runner.py" -v

echo "[4/9] test_fuzzy_30.py"
"$VENV_PY" "$ROOT_DIR/scripts/test_fuzzy_30.py"

echo "[5/9] test_live_capture.py"
"$VENV_PY" "$ROOT_DIR/scripts/test_live_capture.py"

echo "[6/9] test_routing.py"
"$VENV_PY" "$ROOT_DIR/scripts/test_routing.py"

echo "[7/9] smoke_test_routing.py"
"$VENV_PY" "$ROOT_DIR/scripts/smoke_test_routing.py"

echo "[8/9] smoke_test_e2e_50.py"
"$VENV_PY" "$ROOT_DIR/scripts/smoke_test_e2e_50.py"

echo "[9/9] stress_test_d6.py"
"$VENV_PY" "$ROOT_DIR/scripts/stress_test_d6.py"

echo "[DEPLOY GATE] OK - Golden30 + routing smoke testi so uspešni."
