#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"

fail() {
  echo "FAIL | $1"
  exit 1
}

pass() {
  echo "PASS | $1"
}

json_post() {
  local path="$1"
  local payload="$2"
  curl -sS -X POST "$BASE_URL$path" \
    -H "Content-Type: application/json" \
    -d "$payload"
}

echo "[SANITY] BASE_URL=$BASE_URL"

health_code=$(curl -sS -o /tmp/sanity_health.json -w "%{http_code}" "$BASE_URL/health")
[[ "$health_code" == "200" ]] || fail "/health http=$health_code"
pass "/health"

if [[ -n "$ADMIN_TOKEN" ]]; then
  admin_code=$(curl -sS -o /tmp/sanity_admin.json -w "%{http_code}" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$BASE_URL/api/admin/reservations?limit=5")
  [[ "$admin_code" == "200" ]] || fail "admin reservations http=$admin_code"
  pass "admin reservations"
else
  echo "SKIP | admin reservations (ADMIN_TOKEN ni nastavljen)"
fi

booking_resp=$(json_post "/chat/" '{"message":"rad bi se narocil na ortopedski pregled","session_id":"sanity-booking"}')
echo "$booking_resp" | rg -qi "ortoped|datum|termin|naro" || fail "booking flow response"
pass "chat booking"

interrupt_resp=$(json_post "/chat/" '{"message":"imam parking?","session_id":"sanity-booking"}')
echo "$interrupt_resp" | rg -qi "parkir|parking" || fail "chat interrupt/info response"
pass "chat interrupt/info"

info_resp=$(json_post "/chat/" '{"message":"kdaj ste odprti?","session_id":"sanity-info"}')
echo "$info_resp" | rg -qi "odprt|ponedelj|petek|delovni" || fail "chat general info response"
pass "chat general info"

echo "[SANITY] ALL PASS"
