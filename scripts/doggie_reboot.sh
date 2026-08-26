#!/bin/bash
set -u

REPO_DIR="${DOGGIE_REPO_DIR:-/home/matt/pidog}"
PYTHON_BIN="${DOGGIE_PYTHON_BIN:-/usr/bin/python3}"
REBOOT_CMD="${DOGGIE_REBOOT_CMD:-/sbin/reboot}"
REBOOT_ARGS="${DOGGIE_REBOOT_ARGS:-}"

cd "$REPO_DIR" || exit 1

echo "Doggie reboot: lowering Doggie through the live safe-shutdown controller."
"$REPO_DIR/scripts/doggie_prepare_shutdown.sh"
systemctl stop pidog-gpt.service

echo "Doggie reboot: restarting the Pi."
exec "$REBOOT_CMD" $REBOOT_ARGS
