#!/usr/bin/env bash
# OMNI launcher for Linux / macOS  (Windows users: use omni.cmd)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
if command -v python3 >/dev/null 2>&1; then
  exec python3 -m omni "$@"
elif command -v python >/dev/null 2>&1; then
  exec python -m omni "$@"
else
  echo "Python 3 not found. Install from https://www.python.org/downloads/"
  exit 1
fi
