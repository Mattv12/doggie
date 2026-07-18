#!/bin/bash
set -u

REPO_DIR="${DOGGIE_REPO_DIR:-/home/matt/pidog}"
PYTHON_BIN="${DOGGIE_PYTHON_BIN:-/usr/bin/python3}"
REBOOT_CMD="${DOGGIE_REBOOT_CMD:-/sbin/reboot}"
REBOOT_ARGS="${DOGGIE_REBOOT_ARGS:-}"
PREP_ARGS="${DOGGIE_REBOOT_PREP_ARGS:-}"

cd "$REPO_DIR" || exit 1

echo "Doggie reboot: asking dog to sit before restart."
if ! "$PYTHON_BIN" -m custom_dog.main prepare-reboot $PREP_ARGS; then
  echo "Doggie reboot: sit prep failed; continuing with system reboot."
fi

echo "Doggie reboot: restarting the Pi."
exec "$REBOOT_CMD" $REBOOT_ARGS
