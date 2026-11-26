#!/usr/bin/env bash
# Compatibility gate: verify the pinned LibreELEC V4L2 DRM PRIME patch
# applies cleanly to the pinned Amlogic FFmpeg source before any full build.
set -euo pipefail

FFMPEG_REPO="https://github.com/chewitt/FFmpeg.git"
FFMPEG_COMMIT="ad8c2e36ee2d5a30442f6e4ca0e82df2622f8958"
LIBREELEC_COMMIT="ceb19682c636ace4d7403d430e7a76c990c62db7"
PATCH_PATH="packages/multimedia/ffmpeg/patches/v4l2-drmprime/0001-v4l2-drmprime.patch"
PATCH_URL="https://raw.githubusercontent.com/LibreELEC/LibreELEC.tv/$LIBREELEC_COMMIT/$PATCH_PATH"

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

git init -q "$WORK_DIR/ffmpeg"
git -C "$WORK_DIR/ffmpeg" remote add origin "$FFMPEG_REPO"
git -C "$WORK_DIR/ffmpeg" fetch --depth=1 origin "$FFMPEG_COMMIT"
git -C "$WORK_DIR/ffmpeg" checkout --detach FETCH_HEAD

curl -fsSL --retry 3 "$PATCH_URL" -o "$WORK_DIR/v4l2-drmprime.patch"

echo "Checking patch against FFmpeg commit $FFMPEG_COMMIT"
git -C "$WORK_DIR/ffmpeg" apply --check "$WORK_DIR/v4l2-drmprime.patch"
git -C "$WORK_DIR/ffmpeg" apply "$WORK_DIR/v4l2-drmprime.patch"
git -C "$WORK_DIR/ffmpeg" diff --check

if ! grep -R -q "AV_PIX_FMT_DRM_PRIME" \
    "$WORK_DIR/ffmpeg/libavcodec/v4l2_buffers.c" \
    "$WORK_DIR/ffmpeg/libavcodec/v4l2_m2m_dec.c"; then
    echo "Patch applied but DRM PRIME decoder output was not found." >&2
    exit 1
fi

echo "PASS: pinned patch applies and adds V4L2 DRM PRIME frame handling."
git -C "$WORK_DIR/ffmpeg" diff --stat
