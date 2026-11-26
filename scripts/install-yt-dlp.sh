#!/bin/sh
# Install the official latest yt-dlp Linux ARM64 standalone binary for RoxyTube.
# No sudo and no system-wide files are modified.
set -eu
umask 077

for command in curl python3 sha256sum; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "Missing required command: $command" >&2
        exit 1
    }
done

ARCH="$(uname -m)"
case "$ARCH" in
    aarch64|arm64) ASSET="yt-dlp_linux_aarch64" ;;
    *)
        echo "Unsupported architecture: $ARCH (RoxyTube target is Linux aarch64)." >&2
        exit 1
        ;;
esac

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
DEST_DIR="$DATA_HOME/roxy-youtube-tv/bin"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

curl -fsSL --retry 3 \
    https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest \
    -o "$TMP_DIR/release.json"

TAG="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["tag_name"])' "$TMP_DIR/release.json")"
case "$TAG" in
    ""|*[!0-9.]*)
        echo "Unexpected yt-dlp release tag: $TAG" >&2
        exit 1
        ;;
esac

BASE_URL="https://github.com/yt-dlp/yt-dlp/releases/download/$TAG"
curl -fsSL --retry 3 "$BASE_URL/$ASSET" -o "$TMP_DIR/$ASSET"
curl -fsSL --retry 3 "$BASE_URL/SHA2-256SUMS" -o "$TMP_DIR/SHA2-256SUMS"

EXPECTED="$(awk -v asset="$ASSET" '$2 == asset { print $1; exit }' "$TMP_DIR/SHA2-256SUMS")"
if [ -z "$EXPECTED" ]; then
    echo "Official SHA2-256SUMS does not contain $ASSET for $TAG." >&2
    exit 1
fi

ACTUAL="$(sha256sum "$TMP_DIR/$ASSET" | awk '{print $1}')"
if [ "$ACTUAL" != "$EXPECTED" ]; then
    echo "Checksum verification failed for yt-dlp $TAG." >&2
    exit 1
fi

mkdir -p "$DEST_DIR"
install -m 0755 "$TMP_DIR/$ASSET" "$TMP_DIR/yt-dlp"
mv -f "$TMP_DIR/yt-dlp" "$DEST_DIR/yt-dlp"

echo "Installed yt-dlp $TAG"
echo "Path: $DEST_DIR/yt-dlp"
"$DEST_DIR/yt-dlp" --version
