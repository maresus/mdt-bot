#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_FILE="$ROOT_DIR/runtime.txt"
STRICT_ENV_CHECK="${STRICT_ENV_CHECK:-false}"

required_env=(
  OPENAI_API_KEY
  DATABASE_URL
  ADMIN_TOKEN
  RESEND_API_KEY
)

sms_env=(
  TWILIO_ACCOUNT_SID
  TWILIO_AUTH_TOKEN
  TWILIO_PHONE_NUMBER
)

check_runtime_pin() {
  if [[ ! -f "$RUNTIME_FILE" ]]; then
    echo "[D7] runtime.txt manjka"
    return 1
  fi

  local runtime_value
  runtime_value="$(tr -d '[:space:]' < "$RUNTIME_FILE")"

  if [[ ! "$runtime_value" =~ ^python-3\.12(\.[0-9]+)?$ ]]; then
    echo "[D7] runtime.txt mora biti pinan na python-3.12.x (trenutno: $runtime_value)"
    return 1
  fi

  echo "[D7] runtime pin OK: $runtime_value"
}

check_env_group() {
  local group_name="$1"
  shift
  local missing=0

  echo "[D7] Preverjam env skupino: $group_name"
  for var in "$@"; do
    if [[ -z "${!var:-}" ]]; then
      echo "  - MISSING: $var"
      missing=1
    else
      echo "  - OK: $var"
    fi
  done

  return $missing
}

run_gates() {
  echo "[D7] Zagon polnega deploy gate"
  "$ROOT_DIR/scripts/deploy_gate_full.sh"
}

main() {
  echo "[D7] FINAL GATE START"
  check_runtime_pin
  run_gates

  if [[ "$STRICT_ENV_CHECK" == "true" ]]; then
    echo "[D7] STRICT_ENV_CHECK=true -> env check je obvezen"
    check_env_group "core" "${required_env[@]}"

    local sms_enabled="${ENABLE_SMS_REMINDERS:-false}"
    local sms_mock="${SMS_MOCK_MODE:-false}"
    if [[ "$sms_enabled" == "true" && "$sms_mock" != "true" ]]; then
      check_env_group "sms" "${sms_env[@]}"
    else
      echo "[D7] SMS env check preskocen (ENABLE_SMS_REMINDERS=$sms_enabled, SMS_MOCK_MODE=$sms_mock)"
    fi
  else
    echo "[D7] STRICT_ENV_CHECK=false -> env check je informativen"
    check_env_group "core" "${required_env[@]}" || true
  fi

  cat <<'MSG'
[D7] FINAL GATE PASS
Naslednji koraki:
1) git push origin main
2) Railway deploy iz main
3) 60 min live opazovanje:
   - /health endpoint
   - admin rezervacije create/confirm/reject
   - 3 real chat flow testi (booking, interrupt, info)
MSG
}

main "$@"
