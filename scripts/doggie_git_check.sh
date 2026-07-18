#!/bin/bash
set -u

REPO_DIR="${DOGGIE_REPO_DIR:-/home/matt/pidog}"
REPO_OWNER="${DOGGIE_REPO_OWNER:-}"
BRANCH="${DOGGIE_BRANCH:-main}"
GIT_TIMEOUT="${DOGGIE_GIT_TIMEOUT:-20}"

cd "$REPO_DIR" || {
  echo "doggie git check: repo dir not found: $REPO_DIR"
  exit 1
}

if [ -z "$REPO_OWNER" ]; then
  REPO_OWNER="$(stat -c '%U' "$REPO_DIR" 2>/dev/null || echo root)"
fi

run_git() {
  if [ "$(id -u)" -eq 0 ] && [ "$REPO_OWNER" != "root" ]; then
    timeout "$GIT_TIMEOUT" sudo -u "$REPO_OWNER" "$@"
  else
    timeout "$GIT_TIMEOUT" "$@"
  fi
}

echo "== doggie git check =="
echo "repo: $REPO_DIR"

if ! run_git git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "FAIL: not a git repository"
  exit 1
fi

origin_url="$(run_git git remote get-url origin 2>/dev/null || true)"
if [ -z "$origin_url" ]; then
  echo "FAIL: git remote 'origin' is not configured"
  exit 1
fi

echo "origin: $origin_url"
echo "branch: $BRANCH"

if ping -c 1 -W 1 github.com >/dev/null 2>&1; then
  echo "network: github.com reachable"
else
  echo "FAIL: github.com is not reachable from the Pi"
  exit 1
fi

if run_git git ls-remote --exit-code origin "$BRANCH" >/dev/null 2>&1; then
  echo "remote: origin/$BRANCH reachable"
else
  echo "FAIL: could not query origin/$BRANCH"
  exit 1
fi

head_commit="$(run_git git rev-parse --short HEAD 2>/dev/null || true)"
remote_commit="$(run_git git ls-remote origin "$BRANCH" 2>/dev/null | awk 'NR==1 {print substr($1,1,7)}')"

if [ -n "$head_commit" ]; then
  echo "local HEAD: $head_commit"
fi
if [ -n "$remote_commit" ]; then
  echo "remote HEAD: $remote_commit"
fi

echo "PASS: doggie can communicate with git origin"
