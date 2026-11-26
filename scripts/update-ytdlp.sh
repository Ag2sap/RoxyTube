#!/bin/sh
set -eu

VENV_BIN="/home/Applications/.venv/bin"
if [ -x "$VENV_BIN/python" ]; then
    PYTHON="$VENV_BIN/python"
else
    PYTHON="$(command -v python3 || true)"
fi

if [ -z "$PYTHON" ] || [ ! -x "$PYTHON" ]; then
    echo "yt-dlp updater: Python 3.11+ tidak ditemukan." >&2
    exit 127
fi

"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else "yt-dlp terbaru memerlukan Python 3.11+")'

"$PYTHON" -m pip install --upgrade "yt-dlp>=2026.11.23"

if [ -x "$VENV_BIN/yt-dlp" ]; then
    YTDLP="$VENV_BIN/yt-dlp"
else
    YTDLP="$(command -v yt-dlp || true)"
fi

if [ -z "$YTDLP" ]; then
    echo "yt-dlp berhasil dipasang tetapi executable tidak ditemukan pada PATH." >&2
    exit 1
fi

echo "Executable: $YTDLP"
"$YTDLP" --version
