#!/bin/sh
# Install a GitHub Actions DRM PRIME runtime artifact into RoxyTube's user-local data.
# Usage: sh scripts/install-drmprime-runtime.sh /path/to/roxytube-mpv-drmprime-aarch64.tar.gz
set -eu
umask 077

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then
    echo "Usage: sh scripts/install-drmprime-runtime.sh /path/to/roxytube-mpv-drmprime-aarch64.tar.gz" >&2
    exit 2
fi

for command in tar sha256sum; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "Missing required command: $command" >&2
        exit 1
    }
done

CHECKSUM_FILE="$ARCHIVE.sha256"
if [ ! -f "$CHECKSUM_FILE" ]; then
    echo "Checksum file not found: $CHECKSUM_FILE" >&2
    exit 1
fi

ARCHIVE_DIR="$(CDPATH= cd -- "$(dirname -- "$ARCHIVE")" && pwd)"
ARCHIVE_BASE="$(basename -- "$ARCHIVE")"
(
    cd "$ARCHIVE_DIR"
    sha256sum -c "$(basename -- "$CHECKSUM_FILE")"
)

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

tar -tzf "$ARCHIVE" | grep -q '^runtime/bin/mpv$' || {
    echo "Archive does not contain runtime/bin/mpv." >&2
    exit 1
}
tar -xzf "$ARCHIVE" -C "$TMP_DIR"
[ -x "$TMP_DIR/runtime/bin/mpv" ] || {
    echo "Extracted MPV wrapper is missing or not executable." >&2
    exit 1
}

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
DEST_PARENT="$DATA_HOME/roxy-youtube-tv"
DEST="$DEST_PARENT/runtime"
mkdir -p "$DEST_PARENT"

if [ -e "$DEST" ]; then
    BACKUP="$DEST_PARENT/runtime.backup.$$"
    mv "$DEST" "$BACKUP"
    echo "Previous app-local runtime backed up to: $BACKUP"
fi

mv "$TMP_DIR/runtime" "$DEST"
echo "Installed app-local DRM PRIME runtime: $DEST"
"$DEST/bin/mpv" --version | head -n 2
echo "Opt-in launch: ROXY_ENABLE_DRMPRIME=1 sh scripts/run.sh"
