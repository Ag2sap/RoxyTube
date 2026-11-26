#!/bin/sh
# Safe, user-local deployment of the RoxyTube integration branch to HG680P.
# No sudo, system package changes, service restarts, or DRM PRIME runtime switch.
set -eu

APP_ROOT="${ROXYTUBE_ROOT:-/home/Applications/RoxyTube}"
TARGET_BRANCH="feature/channel-playback-ytdlp-opt"
PYTHON="/home/Applications/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

if [ "$(id -un)" != "roxy" ]; then
    echo "Run this script as user roxy; do not use sudo." >&2
    exit 1
fi
if [ ! -d "$APP_ROOT/.git" ]; then
    echo "RoxyTube git repository not found at $APP_ROOT." >&2
    echo "Set ROXYTUBE_ROOT if the installation is elsewhere." >&2
    exit 1
fi
if ! command -v git >/dev/null 2>&1; then
    echo "git is required." >&2
    exit 1
fi

cd "$APP_ROOT"
if [ -n "$(git status --porcelain)" ]; then
    echo "STOP: the working tree has local changes or untracked files." >&2
    echo "Nothing was changed. Review/commit or back up those changes first." >&2
    git status --short >&2
    exit 1
fi

OLD_BRANCH="$(git branch --show-current)"
OLD_SHA="$(git rev-parse HEAD)"
BACKUP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/roxy-youtube-tv/backups"
mkdir -p "$BACKUP_DIR"
BUNDLE="$BACKUP_DIR/roxytube-before-channel-playback-$OLD_SHA.bundle"
git bundle create "$BUNDLE" --all
echo "Git backup created: $BUNDLE"
echo "Previous checkout: $OLD_BRANCH ($OLD_SHA)"

git fetch --prune origin "$TARGET_BRANCH"
git checkout -B "$TARGET_BRANCH" FETCH_HEAD

# These installers are app-local and checksum-verified; they do not use sudo.
sh scripts/install-yt-dlp.sh
sh scripts/install-deno.sh

"$PYTHON" -m py_compile app/main.py
"$PYTHON" -m unittest discover -s tests -v
sh -n scripts/run.sh
sh -n scripts/install-yt-dlp.sh
sh -n scripts/install-deno.sh

echo
echo "RoxyTube source deployment and local checks completed."
echo "System MPV is unchanged. DRM PRIME runtime is NOT enabled by this script."
echo "Launch from the existing X/Openbox session with:"
echo "  cd '$APP_ROOT' && sh scripts/run.sh"
echo
echo "Rollback source checkout if needed:"
echo "  cd '$APP_ROOT' && git checkout --detach '$OLD_SHA'"
echo "Git bundle backup: $BUNDLE"
