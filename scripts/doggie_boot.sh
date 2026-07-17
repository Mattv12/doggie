#!/bin/bash
set -u

REPO_DIR="${DOGGIE_REPO_DIR:-/home/matt/pidog}"
REPO_OWNER="${DOGGIE_REPO_OWNER:-}"
BRANCH="${DOGGIE_BRANCH:-main}"
PYTHON_BIN="${DOGGIE_PYTHON_BIN:-/usr/bin/python3}"
NETWORK_TIMEOUT="${DOGGIE_NETWORK_TIMEOUT:-20}"
PULL_TIMEOUT="${DOGGIE_PULL_TIMEOUT:-25}"
BOOT_ARGS="${DOGGIE_BOOT_ARGS:-}"

cd "$REPO_DIR" || exit 1

if [ -z "$REPO_OWNER" ]; then
  REPO_OWNER="$(stat -c '%U' "$REPO_DIR" 2>/dev/null || echo root)"
fi

git_pull() {
  if [ "$(id -u)" -eq 0 ] && [ "$REPO_OWNER" != "root" ]; then
    timeout "$PULL_TIMEOUT" sudo -u "$REPO_OWNER" git pull --ff-only origin "$BRANCH"
  else
    timeout "$PULL_TIMEOUT" git pull --ff-only origin "$BRANCH"
  fi
}

echo "Doggie boot: waiting up to ${NETWORK_TIMEOUT}s for internet..."
deadline=$((SECONDS + NETWORK_TIMEOUT))
while [ "$SECONDS" -lt "$deadline" ]; do
  if ping -c 1 -W 1 github.com >/dev/null 2>&1; then
    echo "Doggie boot: internet ready."
    break
  fi
  sleep 1
done

if ping -c 1 -W 1 github.com >/dev/null 2>&1; then
  echo "Doggie boot: pulling ${BRANCH}..."
  git_pull || echo "Doggie boot: git pull skipped or failed."
else
  echo "Doggie boot: no internet yet, starting local code."
fi

echo "Doggie boot: launching custom dog."
exec "$PYTHON_BIN" -m custom_dog.main boot $BOOT_ARGS
