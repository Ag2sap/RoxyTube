#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
PYTHON="/home/Applications/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then PYTHON="python3"; fi
exec "$PYTHON" app/main.py "$@"
