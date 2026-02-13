#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
MCP_URL="${MCP_URL:-http://localhost:7001}"

wait_for_http() {
  local name="$1"
  local url="$2"
  local max_attempts="${3:-60}"
  local attempt=1
  while [[ "$attempt" -le "$max_attempts" ]]; do
    if curl -fsS "$url" >/dev/null; then
      echo "[ok] $name is reachable: $url"
      return 0
    fi
    sleep 2
    attempt=$((attempt + 1))
  done
  echo "[error] Timed out waiting for $name at $url"
  return 1
}

assert_ok_true() {
  local name="$1"
  local json_payload="$2"
  if ! echo "$json_payload" | grep -Eq '"ok"[[:space:]]*:[[:space:]]*true'; then
    echo "[error] $name did not return ok:true"
    echo "$json_payload"
    return 1
  fi
  echo "[ok] $name returned ok:true"
}

echo "[step] Bringing stack up..."
docker compose up -d --build

echo "[step] Waiting for health endpoints..."
wait_for_http "backend health" "$BACKEND_URL/health"
wait_for_http "backend status" "$BACKEND_URL/status"
wait_for_http "mcp health" "$MCP_URL/health"

echo "[step] Verifying therapist_search tool..."
THERAPIST_RESP="$(
  curl -fsS -X POST "$MCP_URL/tools/therapist_search" \
    -H "Content-Type: application/json" \
    -d '{"location_text":"Stockholm","radius_km":5,"limit":3}'
)"
assert_ok_true "therapist_search" "$THERAPIST_RESP"

echo "[step] Verifying send_email tool..."
SEND_EMAIL_RESP="$(
  curl -fsS -X POST "$MCP_URL/tools/send_email" \
    -H "Content-Type: application/json" \
    -d '{"to":"dummy@example.com","subject":"Dev verify","body":"Mailtrap dev verification."}'
)"
assert_ok_true "send_email" "$SEND_EMAIL_RESP"

echo "[done] Dev verification passed."
