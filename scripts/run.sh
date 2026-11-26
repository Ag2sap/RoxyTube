#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
VENV_BIN="/home/Applications/.venv/bin"
PYTHON="$VENV_BIN/python"
if [ -x "$PYTHON" ]; then
    PATH="$VENV_BIN:$PATH"
    export PATH
else
    PYTHON="$(command -v python3 || true)"
    if [ -z "$PYTHON" ]; then
        echo "RoxyTube: python3 tidak ditemukan." >&2
        exit 127
    fi
fi
exec "$PYTHON" app/main.py "$@"
