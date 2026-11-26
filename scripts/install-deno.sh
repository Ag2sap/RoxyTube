#!/bin/sh
# Install the official Deno ARM64 binary into RoxyTube's app-local runtime.
# No sudo, shell profile edits, or system-wide PATH changes.
set -eu
umask 077

for command in curl python3 unzip sha256sum; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "Missing required command: $command" >&2
        exit 1
    }
done

ARCH="$(uname -m)"
case "$ARCH" in
    aarch64|arm64) ASSET="deno-aarch64-unknown-linux-gnu.zip" ;;
    *)
        echo "Unsupported architecture: $ARCH (RoxyTube target is Linux aarch64)." >&2
        exit 1
        ;;
esac

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
DEST_DIR="$DATA_HOME/roxy-youtube-tv/runtime/bin"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

curl -fsSL --retry 3 \
    https://api.github.com/repos/denoland/deno/releases/latest \
    -o "$TMP_DIR/release.json"
TAG="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["tag_name"])' "$TMP_DIR/release.json")"
case "$TAG" in
    v[0-9]*|[0-9]*) ;;
    *) echo "Unexpected Deno release tag: $TAG" >&2; exit 1 ;;
esac

BASE_URL="https://github.com/denoland/deno/releases/download/$TAG"
curl -fsSL --retry 3 "$BASE_URL/$ASSET" -o "$TMP_DIR/$ASSET"
curl -fsSL --retry 3 "$BASE_URL/$ASSET.sha256sum" -o "$TMP_DIR/$ASSET.sha256sum"

EXPECTED="$(awk 'NF { print $1; exit }' "$TMP_DIR/$ASSET.sha256sum")"
ACTUAL="$(sha256sum "$TMP_DIR/$ASSET" | awk '{print $1}')"
if [ -z "$EXPECTED" ] || [ "$ACTUAL" != "$EXPECTED" ]; then
    echo "Checksum verification failed for Deno $TAG." >&2
    exit 1
fi

unzip -q "$TMP_DIR/$ASSET" -d "$TMP_DIR/unpacked"
[ -f "$TMP_DIR/unpacked/deno" ] || {
    echo "Deno archive did not contain the deno executable." >&2
    exit 1
}
mkdir -p "$DEST_DIR"
install -m 0755 "$TMP_DIR/unpacked/deno" "$DEST_DIR/deno"
echo "Installed app-local Deno $TAG"
echo "Path: $DEST_DIR/deno"
"$DEST_DIR/deno" --version
