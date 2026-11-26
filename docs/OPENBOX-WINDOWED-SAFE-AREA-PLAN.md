# Openbox Windowed Safe Area Plan

- **Branch:** `feat/openbox-windowed-safe-area`
- **Base:** `main` at `6d7fef034f45fd15744d2d32ade2c4597f7d7744`
- **Target:** HG680P / Armbian / X11 / Openbox / LauncherTV
- **Status:** Initial implementation committed; UI controls, automated execution, and device validation remain pending
- **Last updated:** 2026-11-26

## 1. Goal

Correct TV overscan for RoxyTube while retaining the existing LauncherTV + Openbox desktop model. RoxyTube should use a **frameless, ordinary window** whose outer geometry is placed inside a configurable safe rectangle. The application must not depend on an unfinished fullscreen compositor or on the legacy Safe Area Manager frame-resize controller.

XFCE is reference material only. No XFCE component, service, configuration, or dependency is part of the target design.

## 2. Confirmed constraints

- Keep LauncherTV and Openbox as the desktop/launcher environment.
- Do not modify Xorg, XRandR, framebuffer, Openbox configuration, kernel, display drivers, audio configuration, or LauncherTV source in this work.
- Do not change MPV's renderer, decoder, synchronization, yt-dlp, Deno, or DRM PRIME selection as part of Safe Area work.
- Preserve the current MPV process and active stream when changing pages, entering/exiting immersive playback UI, minimizing/restoring, or applying a new window rectangle.
- Preserve mini-player, queue, remote/D-pad navigation, single-instance IPC activation, and minimize/restore behavior.
- Do not deploy to HG680P or restart its application/service without explicit user approval.

## 3. Audit findings on the base commit

- RoxyTube already sets `Qt.FramelessWindowHint`.
- Startup currently resizes the window to 700×525, with min/max bounds 560×420 and 900×675.
- `safe_area_margins()` reads `~/.config/roxy-display/safe-area.json` as percentage values (0–15).
- `apply_safe_area()` only adds margins to the root Qt layout. It does **not** move or resize the outer window and therefore is not a reliable display overscan correction.
- Playback immersive/fullscreen UI currently calls `showFullScreen()`; exit, minimize/restore, and single-instance IPC contain additional fullscreen state handling.
- MPV is a separate process. Safe Area changes must be window/UI geometry operations only and must not recreate or terminate that process.

## 4. Target behavior

### 4.1 Window geometry

- Keep RoxyTube frameless and windowed during normal use and playback.
- Calculate the safe rectangle from the active display geometry and pixel margins:
  - `x = left`
  - `y = top`
  - `width = display_width - left - right`
  - `height = display_height - top - bottom`
- Clamp margins so the resulting rectangle remains valid and respects Qt's minimum-size constraints. If the safe rectangle is too small, report/retain a valid fallback rather than silently applying invalid geometry.
- Apply geometry after the window is mapped and after display/profile changes. Do not use EWMH fullscreen or maximized state as the overscan mechanism.
- Keep the existing frameless window hint. Do not alter Openbox settings to force placement.

### 4.2 Pixel profiles

Use pixel units rather than percentages. Keep profiles per display resolution so RCA and HDMI can be calibrated independently.

Initial **candidate only**, based on the user's remembered XFCE workspace-margin values:

| Display mode | Left | Top | Right | Bottom | Resulting safe rectangle |
|---|---:|---:|---:|---:|---|
| RCA 720×576 | 45 px | 10 px | 45 px | 10 px | x=45, y=10, 630×556 |
| HDMI 1920×1080 | 0 px | 0 px | 0 px | 0 px | full display; calibrate separately |

The RCA values are not confirmed final calibration. Validate all four edges on the actual TV. XFCE workspace margins are only the source of the candidate numbers, not a runtime dependency or proof of overscan correction.

### 4.3 Playback and interaction

- Convert the existing playback fullscreen control into an **immersive playback UI mode**: hide/show surrounding controls inside the same window without calling `showFullScreen()`, `setWindowState(Qt.WindowFullScreen)`, or `showMaximized()`.
- Back/Escape exits immersive UI or returns to results according to the current navigation flow.
- Minimize/restore and single-instance IPC always restore the saved safe-window geometry.
- Do not change MPV process lifecycle, IPC, playback queue, or stream selection.
- Keep the mini-player and D-pad focus paths intact.

### 4.4 Configuration ownership

- First make RoxyTube's local pixel-profile configuration self-contained and backward-compatible with the current legacy percentage file where practical.
- Do not silently reinterpret existing percentage settings as pixels.
- Safe Area Manager integration is a later phase. Its current `config/profiles.json` schema uses percentages and its README states that the fullscreen-safe rendering backend is not implemented. Do not claim that the current Manager controls RoxyTube geometry.
- Before integration, agree on a versioned shared pixel-profile contract or implement a deliberate adapter in the Manager. Do not edit the Manager repository as an incidental side effect of this RoxyTube branch.

## 5. Implementation phases

1. **Read-only audit (in progress):** map all fullscreen calls, geometry changes, startup sizing, settings UI, IPC, and MPV lifecycle paths.
2. **Pixel profile model:** add validated per-resolution pixel profiles, atomic persistence, safe defaults, and legacy-config handling.
3. **Window placement:** compute and apply the outer frameless window geometry against the active screen's available geometry; avoid invalid sizes and out-of-screen placement.
4. **Immersive playback UI:** remove OS fullscreen/maximize transitions from playback UI while preserving its hide/show controls and D-pad behavior.
5. **Settings UI:** add compact remote-friendly pixel adjustment controls and profile reset/apply behavior without crowding the main page.
6. **Regression tests:** cover geometry arithmetic/clamping, config validation/migration, startup, resize, minimize/restore, IPC activation, and fullscreen-call absence from normal flows.
7. **Manager integration design:** separately align a shared profile schema with Safe Area Manager. No compositor or legacy frame-resize controller dependency.
8. **Device validation:** only after user approval, test RCA and HDMI geometry, visible edges, remote navigation, MPV stream continuity, mini-player, and minimize/restore on HG680P.

## 6. Acceptance criteria

- On RCA 720×576 with candidate margins, the RoxyTube outer window is placed at (45,10) with size 630×556, subject to actual screen geometry and WM constraints.
- HDMI has an independent profile and is not forced to inherit RCA values.
- No normal playback, immersive UI, minimize/restore, or IPC activation path requests EWMH fullscreen/maximized state.
- MPV PID/session and active stream remain unchanged through UI mode and geometry changes.
- Back/Escape, D-pad, mini-player, queue, and remote controls continue to work.
- Existing playback/yt-dlp/decoder configuration remains untouched.
- Python compile and automated tests pass; device validation is recorded separately and is not inferred from static tests.

## 7. Explicit non-goals

- Implementing an X11 compositor or fullscreen content-capture pipeline.
- Resizing an EWMH fullscreen Openbox frame.
- XFCE installation or XFCE workspace-margin configuration.
- XRandR/Xorg/framebuffer transforms.
- Changes to LauncherTV, Openbox, kernel, drivers, audio, MPV rendering/decoder, yt-dlp, or DRM PRIME.
- Automatic deployment, service installation, or device restart.

## 8. Current progress

- [x] Confirmed current `main` base commit.
- [x] Confirmed frameless window hint and percentage-only inner-layout margins.
- [x] Located fullscreen transitions in playback, restore, and single-instance IPC paths.
- [x] Confirmed Safe Area Manager currently stores percentage profiles and does not yet provide a fullscreen-safe renderer.
- [x] Implement resolution-specific pixel profile loading with separate 720×576 and 1920×1080 defaults.
- [x] Implement outer frameless-window safe geometry and first-show placement.
- [x] Convert the playback expand control to windowed immersive UI (no OS fullscreen request).
- [x] Add remote-friendly pixel adjustment controls and atomic profile persistence; static regression tests updated, execution still pending.
- [ ] Validate on HG680P after explicit deployment approval.


### Initial implementation notes (2026-11-26)

The first implementation commit applies the core windowed approach:

- A new local file, `~/.config/roxy-youtube-tv/window-safe-area.json`, stores versioned pixel profiles keyed by display resolution.
- Built-in 720×576 margins are 45/10/45/10 px as a candidate; 1920×1080 defaults to zero margins.
- The outer frameless window is placed and sized within the safe rectangle, centered if the safe rectangle is larger than the app's existing maximum window size.
- The playback expand control now hides/shows in-window UI only. It does not call `showFullScreen()`.
- Minimize/restore and single-instance activation use windowed geometry.
- README and a JSON example were updated.
- Static playback contract tests were updated to cover pixel-profile persistence, outer geometry, and the absence of OS fullscreen calls. They have not yet been executed in this environment. No claim of runtime or device success is made.
- The Settings page now exposes four pixel spinboxes and a save/apply action for the detected display resolution. Profiles can also be edited directly in JSON.
