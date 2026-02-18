#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$ROOT_DIR/.venv/bin/python"
ONLY="${DEPLOY_GATE_ONLY:-}"
CONTINUE_ON_FAIL="${DEPLOY_GATE_CONTINUE:-false}"

if [[ ! -x "$VENV_PY" ]]; then
  echo "[DEPLOY GATE] .venv manjka. Ustvari ga in namesti dependencies:"
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

export USE_UNIFIED_ROUTER="${USE_UNIFIED_ROUTER:-true}"

echo "[DEPLOY GATE] Root: $ROOT_DIR"
echo "[DEPLOY GATE] USE_UNIFIED_ROUTER=$USE_UNIFIED_ROUTER"
echo "[DEPLOY GATE] ONLY=${ONLY:-<all>}"
echo "[DEPLOY GATE] CONTINUE_ON_FAIL=$CONTINUE_ON_FAIL"

declare -a STEPS=(
  "d3|$VENV_PY $ROOT_DIR/scripts/test_d3_modules.py"
  "golden30|$VENV_PY -m scripts.run_routing_suite --suite tests/golden_30.json --name 'GOLDEN 30'"
  "golden_runner|$VENV_PY -m pytest $ROOT_DIR/tests/test_golden_runner.py -v"
  "fuzzy30|$VENV_PY -m scripts.run_routing_suite --suite tests/fuzzy_30.json --name 'FUZZY 30'"
  "live_capture|$VENV_PY $ROOT_DIR/scripts/test_live_capture.py"
  "routing|$VENV_PY -m scripts.run_routing_suite --suite tests/smoke_routing_40.json --name 'ROUTING 40'"
  "smoke_50|$VENV_PY -m scripts.run_routing_suite --suite tests/smoke_50.json --name 'SMOKE 50'"
  "smoke_110|$VENV_PY -m scripts.run_routing_suite --suite tests/smoke_110.json --name 'SMOKE 110'"
  "smoke_e2e_50|$VENV_PY $ROOT_DIR/scripts/smoke_test_e2e_50.py"
  "stress_d6|$VENV_PY $ROOT_DIR/scripts/stress_test_d6.py"
)

fails=0
total=0
for step in "${STEPS[@]}"; do
  name="${step%%|*}"
  cmd="${step#*|}"
  if [[ -n "$ONLY" && "$name" != "$ONLY" ]]; then
    continue
  fi
  total=$((total + 1))
  echo "[DEPLOY GATE][$total] $name"
  if bash -lc "$cmd"; then
    echo "[DEPLOY GATE] PASS: $name"
  else
    echo "[DEPLOY GATE] FAIL: $name"
    fails=$((fails + 1))
    if [[ "$CONTINUE_ON_FAIL" != "true" ]]; then
      exit 1
    fi
  fi
done

if [[ "$fails" -gt 0 ]]; then
  echo "[DEPLOY GATE] FAIL - failed steps: $fails"
  exit 1
fi

echo "[DEPLOY GATE] OK - Golden30 + routing smoke testi so uspešni."
