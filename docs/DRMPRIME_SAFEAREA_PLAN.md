# RoxyTube — DRM PRIME, yt-dlp, and Safe Area Integration Plan

**Target device:** HG680P / ZTE B860H, Amlogic S905X, Armbian 26.11 Noble, kernel 6.12.114-ophub, Xorg/Openbox, 2 GB RAM.  
**Working branch:** `feature/drmprime-safearea` (branched from `roxytube-safearea`).  
**Scope:** RoxyTube only. Do not modify `main`, LauncherTV, Kodi, Xorg, Openbox, kernel, audio configuration, or system-wide display settings.

## 1. Current repository baseline

The starting `roxytube-safearea` revision already contains:

- PySide6 TV interface, search/channel results, D-pad navigation, embedded MPV, subtitles, queue, and background playback.
- MPV is embedded into the Qt video surface using `--wid`.
- Playback currently launches MPV with `--vo=x11`, ALSA `dmix:CARD=S905XP212,DEV=0`, and no explicit hardware-decoding option.
- RoxyTube currently calculates its playback Safe Area window geometry itself from `~/.config/roxy-display/safe-area.json`. This is a local window-geometry feature, not the validated fullscreen-safe Safe Area solution.
- `scripts/run.sh` runs the shared interpreter at `/home/Applications/.venv/bin/python`, but originally did not prepend that venv's `bin` directory to `PATH`.
- `yt-dlp` is invoked as an external executable through `YTDLP`; the original repository did not install or constrain its version.

This means the current player is a working software/compatibility baseline, not proof that DRM PRIME is active.

## 2. yt-dlp update and runtime consistency

At plan authoring time, the latest official stable upstream release is **2026.11.23**. Use the official upstream release, not an unrelated fork or nightly build, unless a later stable release is available when deployment is performed.

Implementation requirements:

1. Resolve yt-dlp from the shared `/home/Applications/.venv/bin` first, while retaining `ROXY_YT_DLP` as an explicit override.
2. Provide a repeatable update/install script that installs or upgrades yt-dlp in the shared venv and prints `yt-dlp --version` afterward.
3. Do not silently update the shared venv every time RoxyTube starts.
4. Check Python compatibility before installation. Current upstream releases require Python 3.11 or newer.
5. Keep metadata extraction and MPV's yt-dlp integration on the same executable/version to avoid inconsistent extractor behavior.
6. Add a diagnostic output or log entry showing the resolved yt-dlp path and version.

Initial Stage A changes now present in this branch:

- `requirements.txt` declares `yt-dlp>=2026.11.23`.
- `scripts/run.sh` prepends the shared venv `bin` directory to `PATH` when the shared interpreter exists.
- `scripts/update-ytdlp.sh` upgrades yt-dlp in the shared venv (or the active Python fallback), checks Python 3.11+, and prints the executable path/version.

Acceptance checks still required on HG680P:

- `command -v yt-dlp` resolves to the shared venv when launched by RoxyTube.
- `yt-dlp --version` reports the installed official stable version.
- Search, channel lookup, metadata retrieval, subtitle listing, and MPV playback all use the same executable.
- An unavailable or outdated executable produces a clear status message rather than a silent failure.

## 3. DRM PRIME / Amlogic hardware-decoding investigation

Do not assume that the string `drmprime` is a supported MPV `--hwdec` value on this device. MPV's current documented Linux hardware-decoding API includes `drm` and requires a compatible `--vo=gpu` or `--vo=gpu-next`; older FFmpeg/V4L2 builds may expose different names and paths. The HG680P's actual MPV, FFmpeg, Mesa/Panfrost, and kernel decoder capabilities must decide the implementation.

A read-only diagnostic helper, `scripts/diagnose-video-hw.sh`, is now included. Run it inside the existing X11 session as the normal `roxy` user. It reports MPV/FFmpeg capabilities, V4L2 devices, device-node permissions, relevant modules, display environment, and GLX details when available. It does not install packages or change system configuration.

Before changing playback defaults, collect on the device:

- `mpv --version` and `mpv --hwdec=help` (or the build's equivalent).
- `ffmpeg -version` and available hardware accelerators / decoders.
- `v4l2-ctl --list-devices` and decoder capabilities for the detected `meson-vdec` device, if present.
- `ls -l /dev/dri /dev/video*` and the `roxy` user's access to required device nodes.
- Relevant MPV logs for a controlled H.264 test clip, including the selected decoder, video output, and any fallback reason.

Implementation sequence:

1. Preserve the current `--vo=x11` software-compatible path as the guaranteed fallback.
2. Add an opt-in hardware-decoding mode only after the installed MPV build confirms the exact supported API.
3. Test the appropriate GPU output/context required by that MPV build. Do not switch blindly from `--vo=x11` to `--vo=gpu`; verify Qt `--wid` embedding, X11 context creation, subtitles, scaling, and remote responsiveness.
4. If the decoder exposes a V4L2 stateful path rather than MPV's supported DRM hwdec API, document the missing component/build requirement instead of passing an unsupported `drmprime` option.
5. Log the selected hardware decoder and whether frames are actually decoded in hardware. A successful MPV launch alone is not proof of hardware decoding.
6. Keep an automatic fallback to the existing software path when hardware initialization fails. Never leave the playback UI stuck on a black screen after a failed hardware attempt.

Acceptance checks:

- H.264 playback is confirmed with MPV logs showing the intended hardware decoder and no software fallback.
- CPU usage and playback smoothness are measured against the software baseline.
- 4:3 and 16:9 content, subtitles, seek, pause, queue/next, background playback, and the actual HG remote remain functional.
- Unsupported codecs or decoder failures fall back cleanly to software decoding.

## 4. Safe Area Manager integration — blocked pending renderer

The current Safe Area Manager repository (`Ag2sap/Safe-Area-Manager-With-Controller`) is presently a profile editor plus an unfinished rendering backend. Its README states that saving a profile updates configuration only; there is no validated runtime IPC/API for applications to request or apply Safe Area. Its ADR-0001 proposes a compositor-backed fullscreen rendering stage and explicitly rejects resizing the Openbox frame or removing EWMH fullscreen.

Consequently, **do not implement a guessed IPC/API or claim RoxyTube is integrated yet**. The current RoxyTube `safe-area.json` geometry logic expands a normal frameless window and does not meet the manager's fullscreen-preservation requirement. Keep it as the existing compatibility behavior until the Manager's compositor/rendering backend is implemented and validated.

Required sequence:

1. Complete and validate the Safe Area Manager's fullscreen-safe renderer on a separate branch in that repository. Preserve EWMH fullscreen and the 720×576 client geometry while rendering content inside the configured rectangle.
2. Define and document the actual runtime contract (profile source, eligible-window identification, lifecycle, input-coordinate mapping, and restore behavior) in the Manager repository.
3. Only then adapt RoxyTube to that published contract. Do not add a second global geometry controller, private dispatcher, or another service inside RoxyTube.
4. Keep MPV embedded in the Qt video surface; the managed top-level window is RoxyTube, not a separate MPV window.
5. Preserve D-pad focus, keyboard/IR input, controls auto-hide, playback lifecycle, and the previous window state.
6. Retain the existing local `safe-area.json` behavior only as a clearly documented fallback for standalone use, never concurrently with the manager renderer.
7. Do not change Xorg, Openbox, display modes, kernel, drivers, or system-wide configuration as part of the RoxyTube repository change.

Acceptance checks:

- Home/search remains usable and fullscreen lifecycle is unchanged.
- Playback Safe Area is rendered by the Manager backend while the client remains EWMH fullscreen.
- Back/restore returns to the prior state without moving or resizing unrelated applications.
- D-pad/IR input maps correctly to the visible safe rectangle.
- The Manager can later manage other applications without RoxyTube-specific global logic.

## 5. Work stages and test gates

| Stage | Work | Gate |
|---|---|---|
| A | Add yt-dlp resolver, updater, and version diagnostics | Shared venv path/version verified; search and metadata smoke tests pass |
| B | Collect read-only hardware diagnostics; add opt-in decoder only after capability confirmation | Exact supported decoder/output confirmed on HG680P |
| C | Implement and benchmark hardware path with software fallback | Real H.264 hardware decode confirmed; no regression in UI/audio/remote |
| D1 | Implement and validate Safe Area Manager fullscreen renderer and publish its runtime contract | EWMH fullscreen/client geometry preserved; input and rendering tests pass |
| D2 | Integrate RoxyTube with the published Manager contract | Manager owns fullscreen rendering; restore and D-pad tests pass |
| E | Regression and deployment notes | Device test checklist complete; no system config changed without explicit approval |

Do not combine a speculative decoder change with the yt-dlp update. Safe Area integration in RoxyTube is blocked until Stage D1 is complete. Each stage must remain independently testable and revertible.

## 6. Device regression checklist

- [ ] Python version is 3.11 or newer.
- [ ] Shared venv contains the current official stable yt-dlp.
- [ ] RoxyTube resolves the same yt-dlp executable for search, metadata, subtitles, and MPV.
- [ ] Search results and channel results load.
- [ ] MPV embeds in the Qt video surface.
- [ ] H.264 hardware decode is proven in logs (not inferred).
- [ ] Software fallback works when hardware decode is unavailable.
- [ ] Audio remains on the verified ALSA dmix route.
- [ ] D-pad navigation, seek, pause, subtitle selection, queue, and next-video work.
- [ ] Safe Area enter/exit and window restoration work through the validated Manager renderer.
- [ ] No changes were made to LauncherTV, Kodi, Xorg, Openbox, kernel, drivers, or system audio.

## References

- yt-dlp official releases: https://github.com/yt-dlp/yt-dlp/releases
- MPV manual (hardware decoding and video outputs): https://mpv.io/manual/stable/
- Safe Area Manager repository: https://github.com/Ag2sap/Safe-Area-Manager-With-Controller
- Safe Area Manager ADR-0001: https://github.com/Ag2sap/Safe-Area-Manager-With-Controller/blob/main/docs/architecture/ADR-0001-fullscreen-safe-area-rendering.md
- Amlogic S905X / Armbian meson-vdec reference implementation: https://github.com/dogukangecko/kodi-hwdec-amlogic-armbian
