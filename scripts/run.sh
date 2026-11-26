#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

# DRM PRIME is opt-in. The normal launcher keeps using the current system MPV.
if [ "${ROXY_ENABLE_DRMPRIME:-0}" = "1" ]; then
    DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
    DRM_MPV="$DATA_HOME/roxy-youtube-tv/runtime/bin/mpv"
    if [ ! -x "$DRM_MPV" ]; then
        echo "DRM PRIME runtime is not installed. Run scripts/install-drmprime-runtime.sh first." >&2
        exit 1
    fi
    export ROXY_MPV="$DRM_MPV"
    export ROXY_MPV_HWDEC="${ROXY_MPV_HWDEC:-v4l2m2m}"
    export ROXY_MPV_GPU_HWDEC_INTEROP="${ROXY_MPV_GPU_HWDEC_INTEROP:-drmprime}"
    export ROXY_MPV_VO="${ROXY_MPV_VO:-gpu}"
    export ROXY_MPV_GPU_CONTEXT="${ROXY_MPV_GPU_CONTEXT:-x11egl}"
    export ROXY_MPV_GPU_API="${ROXY_MPV_GPU_API:-opengl}"
fi

PYTHON="/home/Applications/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then PYTHON="python3"; fi
exec "$PYTHON" app/main.py "$@"
