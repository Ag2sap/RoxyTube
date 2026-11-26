#!/bin/sh
# Read-only capability report for the HG680P hardware-decoding investigation.
set -u

section() {
    printf '\n===== %s =====\n' "$1"
}

run_report() {
    label="$1"
    shift
    section "$label"
    if command -v "$1" >/dev/null 2>&1; then
        "$@" 2>&1 || true
    else
        printf '%s: command not found\n' "$1"
    fi
}

section "SYSTEM"
uname -a 2>&1 || true
printf 'User: '
id 2>&1 || true

run_report "MPV VERSION" mpv --version
run_report "MPV HWDEC OPTIONS" mpv --hwdec=help
run_report "MPV VIDEO OUTPUTS" mpv --vo=help
run_report "FFMPEG VERSION" ffmpeg -version
run_report "FFMPEG HARDWARE ACCELERATORS" ffmpeg -hide_banner -hwaccels
run_report "V4L2 DEVICES" v4l2-ctl --list-devices

section "DEVICE NODES AND PERMISSIONS"
ls -l /dev/dri /dev/video* 2>&1 || true

section "RELEVANT KERNEL MODULES"
grep -Ei 'meson|vdec|v4l2|panfrost|drm' /proc/modules 2>/dev/null || true

section "GRAPHICS AND DISPLAY"
printf 'DISPLAY=%s\n' "${DISPLAY-}"
printf 'XDG_SESSION_TYPE=%s\n' "${XDG_SESSION_TYPE-}"
if command -v glxinfo >/dev/null 2>&1; then
    glxinfo -B 2>&1 || true
else
    echo "glxinfo: command not found"
fi

echo
echo "Report complete. This script is read-only; it does not change system configuration."
