#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${DOGGIE_REPO_DIR:-/home/matt/pidog}"
"${REPO_DIR}/scripts/doggie_prepare_shutdown.sh"
systemctl stop pidog-gpt.service
exec /sbin/poweroff
