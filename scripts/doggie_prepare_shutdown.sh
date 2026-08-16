#!/usr/bin/env bash
# Ask the live pidog-gpt controller to lower Doggie safely before power-off.
set -euo pipefail

readonly ENV_FILE="${DOGGIE_ENV_FILE:-/etc/doggie/pidog-gpt.env}"
readonly CONTROL_URL="${DOGGIE_CONTROL_URL:-http://127.0.0.1:8093}"
readonly TIMEOUT_SECONDS="${DOGGIE_SHUTDOWN_TIMEOUT_SECONDS:-20}"

[[ -r "$ENV_FILE" ]] || { echo "Doggie control environment is unavailable." >&2; exit 1; }
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
[[ -n "${DOGGIE_CONTROL_TOKEN:-}" ]] || { echo "Doggie control token is unavailable." >&2; exit 1; }

auth_header="X-Doggie-Control-Token: ${DOGGIE_CONTROL_TOKEN}"
curl --fail --silent --show-error --max-time 3 \
  -X POST -H "$auth_header" "$CONTROL_URL/internal/safe-shutdown" >/dev/null

deadline=$((SECONDS + TIMEOUT_SECONDS))
while (( SECONDS < deadline )); do
  status="$(curl --fail --silent --show-error --max-time 3 -H "$auth_header" \
    "$CONTROL_URL/internal/safe-shutdown-status")" || exit 1
  case "$status" in
    *'"state": "ready"'*)
      echo "Doggie safe shutdown posture complete."
      exit 0
      ;;
    *'"state": "failed"'*)
      echo "Doggie safe shutdown posture failed: $status" >&2
      exit 1
      ;;
  esac
  sleep 0.25
done

echo "Timed out waiting for Doggie's safe shutdown posture." >&2
exit 1
