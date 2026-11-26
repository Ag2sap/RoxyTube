#!/usr/bin/env bash
# Build an isolated ARM64 FFmpeg+MPV runtime with V4L2 DRM PRIME support.
# Build is intentionally opt-in from this experimental branch; system packages stay untouched.
# This never installs or replaces system FFmpeg/MPV.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
WORK="$ROOT/.build-drmprime"
STAGE="$WORK/stage/runtime"
PREFIX="$STAGE"
DIST="$ROOT/dist"

FFMPEG_REPO="https://github.com/chewitt/FFmpeg.git"
FFMPEG_COMMIT="ad8c2e36ee2d5a30442f6e4ca0e82df2622f8958"
LIBREELEC_COMMIT="ceb19682c636ace4d7403d430e7a76c990c62db7"
PATCH_PATH="packages/multimedia/ffmpeg/patches/v4l2-drmprime/0001-v4l2-drmprime.patch"
PATCH_URL="https://raw.githubusercontent.com/LibreELEC/LibreELEC.tv/$LIBREELEC_COMMIT/$PATCH_PATH"
MPV_REPO="https://github.com/mpv-player/mpv.git"
MPV_TAG="v0.42.0"

for command in git curl pkg-config meson ninja make gcc g++; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "Missing build dependency: $command" >&2
        exit 1
    }
done

ARCH="$(uname -m)"
case "$ARCH" in
    aarch64|arm64) ;;
    *) echo "This build targets Linux aarch64, got $ARCH." >&2; exit 1 ;;
esac

rm -rf "$WORK"
mkdir -p "$WORK" "$STAGE" "$DIST"

# Fetch the exact Amlogic FFmpeg source revision used by LibreELEC's S905X family.
git init -q "$WORK/ffmpeg"
git -C "$WORK/ffmpeg" remote add origin "$FFMPEG_REPO"
git -C "$WORK/ffmpeg" fetch --depth=1 origin "$FFMPEG_COMMIT"
git -C "$WORK/ffmpeg" checkout --detach FETCH_HEAD

curl -fsSL --retry 3 "$PATCH_URL" -o "$WORK/v4l2-drmprime.patch"
git -C "$WORK/ffmpeg" apply --check "$WORK/v4l2-drmprime.patch"
git -C "$WORK/ffmpeg" apply "$WORK/v4l2-drmprime.patch"
git -C "$WORK/ffmpeg" diff --check

# Build shared FFmpeg libraries with V4L2 M2M and libdrm enabled.
(
    cd "$WORK/ffmpeg"
    ./configure \
        --prefix="$PREFIX" \
        --libdir="$PREFIX/lib" \
        --pkgconfigdir="$PREFIX/lib/pkgconfig" \
        --arch=aarch64 \
        --target-os=linux \
        --enable-shared \
        --disable-static \
        --enable-gpl \
        --enable-version3 \
        --enable-v4l2-m2m \
        --enable-libdrm \
        --enable-openssl \
        --enable-pic \
        --enable-pthreads \
        --disable-doc \
        --disable-debug
    make -j"$(nproc)"
    make install
)

# Build MPV against the app-local FFmpeg libraries, with EGL/X11 GPU output.
git clone --depth=1 --branch "$MPV_TAG" "$MPV_REPO" "$WORK/mpv"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
export LD_LIBRARY_PATH="$PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
meson setup "$WORK/mpv/build" "$WORK/mpv" \
    --prefix="$PREFIX" \
    --libdir=lib \
    -Dlibmpv=false \
    -Dtests=false \
    -Dmanpage-build=disabled \
    -Dlua=luajit \
    -Djavascript=disabled \
    -Dwayland=disabled \
    -Dx11=enabled \
    -Degl=enabled \
    -Degl-x11=enabled \
    -Dgl=enabled \
    -Ddrm=enabled \
    -Dalsa=enabled
ninja -C "$WORK/mpv/build" -j"$(nproc)"
ninja -C "$WORK/mpv/build" install

# Make the runtime relocatable: resolve the bundled FFmpeg libraries beside mpv.
mv "$PREFIX/bin/mpv" "$PREFIX/bin/mpv.real"
cat > "$PREFIX/bin/mpv" <<'WRAPPER'
#!/bin/sh
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export LD_LIBRARY_PATH="$HERE/../lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$HERE/mpv.real" "$@"
WRAPPER
chmod 0755 "$PREFIX/bin/mpv"

# Fail the build if the intended decoder or DRM PRIME interop was not compiled.
HWDEC_LIST="$("$PREFIX/bin/mpv" --no-config --hwdec=help 2>&1)"
printf '%s\n' "$HWDEC_LIST"
printf '%s\n' "$HWDEC_LIST" | grep -q 'v4l2m2m (' || {
    echo "MPV does not expose the V4L2 M2M decoder." >&2
    exit 1
}
INTEROP_LIST="$("$PREFIX/bin/mpv" --no-config --gpu-hwdec-interop=help 2>&1)"
printf '%s\n' "$INTEROP_LIST"
printf '%s\n' "$INTEROP_LIST" | grep -qi 'drmprime' || {
    echo "MPV does not expose a DRM PRIME GPU interop." >&2
    exit 1
}

cat > "$PREFIX/BUILD-INFO.txt" <<INFO
RoxyTube isolated DRM PRIME runtime
Architecture: aarch64
FFmpeg repository: $FFMPEG_REPO
FFmpeg commit: $FFMPEG_COMMIT
LibreELEC patch commit: $LIBREELEC_COMMIT
MPV tag: $MPV_TAG
Configure: V4L2 M2M + libdrm; MPV EGL/X11 + OpenGL
Runtime is app-local and does not replace system FFmpeg or MPV.
INFO

tar -C "$STAGE/.." -czf "$DIST/roxytube-mpv-drmprime-aarch64.tar.gz" runtime
sha256sum "$DIST/roxytube-mpv-drmprime-aarch64.tar.gz" \
    > "$DIST/roxytube-mpv-drmprime-aarch64.tar.gz.sha256"
echo "Build complete: $DIST/roxytube-mpv-drmprime-aarch64.tar.gz"
