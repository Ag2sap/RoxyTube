# Roxy YouTube — PlasmaTube-style UI migration

## Product decision

Rework the existing Roxy YouTube TV application so its information architecture and visual behavior closely follow KDE PlasmaTube, while keeping the product identity in the header as **YouTube Roxy**.

This is a UI/UX adaptation, not a port of the KDE application and not a dependency on the KDE desktop shell.

## Device constraints

- Target: HG680P / Amlogic S905X / Armbian Noble ARM64
- Memory: 2 GB RAM
- Display: 720x576i PAL, 4:3 television
- Session: Xorg + Openbox
- Existing runtime: Python 3.12, PySide6 6.12, yt-dlp, MPV
- Must remain independent of LauncherTV.
- Do not change Xorg, Openbox, kernel, display driver, audio stack, Kodi, or system-wide packages as part of UI work.

## Visual and interaction direction

Follow PlasmaTube's information architecture and visual language:

- Persistent application header across the full window. Keep YouTube mark and **YouTube Roxy** title.
- Left navigation drawer/sidebar with clear active state and compact/collapsed mode.
- Main feed with responsive video grid; 16:9 thumbnails, duration/live indicator, title and channel metadata.
- Search page with visible search field and optional filters.
- Feed, trending, subscriptions, history, playlists, and channel/detail destinations should use consistent page structure.
- Video details and playback should feel like one application flow, not a detached popup.
- Player view should keep the video prominent, with title/channel, queue/related items, description, subtitle and quality actions.
- Remote-first focus treatment and deterministic D-pad behavior. Back/Escape returns through the page stack; OK activates the focused control.
- Fit 4:3 PAL safe area. Do not assume a widescreen desktop layout.

## Architecture decision

Retain the current PySide6 application shell and its existing yt-dlp/MPV integration for the first migration. Recreate the PlasmaTube-style presentation using existing Qt Widgets rather than introducing the full KDE Frameworks/Kirigami runtime on the 2 GB device.

Keep UI, feed/search data, and playback control separated enough that the interface can be refined without rewriting the media pipeline.

## Playback requirements

- MPV remains the playback engine.
- Playback must remain embedded in the Roxy application window.
- Do not suppress MPV OSC unless an equivalent complete control surface is available and intentionally selected.
- Preserve quality preference and startup fallback behavior.
- Keep subtitle discovery deferred until playback starts; Indonesian tracks should be prioritized when available.
- Do not claim 720p is guaranteed; available formats and device decoding capability determine actual playback.

## Migration scope

1. Establish the shared header, sidebar, page shell, spacing, typography, and focus system.
2. Rebuild feed/search cards and navigation to match the PlasmaTube structure.
3. Rebuild video details/player flow while preserving the existing MPV backend.
4. Wire navigation destinations and empty/loading/error states consistently.
5. Validate Python syntax and static structure; then prepare one integrated device-test revision.

## Safety and delivery

- Work only on `feature/plasmatube-style-ui`.
- Keep `main` and `feature/tv-ui-single-layer` unchanged.
- Do not deploy or pull to HG680P automatically.
- Present the integrated branch for review before any device deployment.
- Preserve the existing local runner change on the HG680P; do not overwrite it during deployment.

## Upstream reference and licensing

KDE PlasmaTube is an independent GPL-3.0-or-later project. This project uses it as a design and architecture reference. Do not copy upstream source files, icons, or artwork into this repository unless the applicable license and attribution requirements are deliberately followed. Prefer an original PySide6 implementation of the same interaction patterns.
