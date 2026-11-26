# RoxyTube

A lightweight YouTube TV-style frontend for HG680P / Armbian Noble (ARM64).

**Status: UI revision for device testing.** This is a standalone app, separate from LauncherTV. It does not modify Xorg, Openbox, kernel, or the existing LauncherTV installation.

## Interface

- Single-window TV interface; no popup keyboard dialog.
- Compact 4:3-oriented window with responsive Safe Area margins.
- Search bar with adjacent keyboard and search controls.
- Integrated on-screen keyboard slides down below the search row and pushes the results area down; SELESAI or Back slides it away.
- Android-TV-inspired keyboard rows with letters, digits, persistent CAPS, one-shot SHIFT, symbol page, comma, period, punctuation, space, backspace, and clear.
- Search results shown as large 16:9 thumbnail cards in a two-column grid on 4:3 layouts, with title, channel/artist and duration.
- Video cards can show the channel avatar as a small overlay at the lower-left of the thumbnail; missing avatars are resolved lazily from channel metadata, one channel lookup at a time.
- A dedicated **Channel** sidebar mode searches YouTube channel results only and shows channel cards with avatar, name, subscriber count and description.
- The playback details row includes a D-pad-focusable channel profile control. The description panel can be expanded while the video surface folds to a compact size; the description remains scrollable.
- Channel-page navigation is prepared as an entry point but the full channel page and its tabs are intentionally deferred to the next development stage.
- D-pad navigation across search controls, keyboard and thumbnail cards, including scrolling the results viewport before focus moves back to the header.
- PlasmaTube-inspired watch page with embedded MPV, a timeline directly below the video, 10-second rewind/forward, playback controls, and a lower queue/description panel.
- D-pad navigation across the timeline, playback controls, queue items, and scrollable description.
- Subtitle choices are enumerated after playback starts; original/manual captions and automatic captions are listed separately when available, with a supported subtitle format selected for each language. The selected track is applied to the active MPV session.
- Quality preference: Auto, 360p, 480p, 720p, or 1080p (limited by formats YouTube exposes). A quality change restarts the stream at the current playback position and reapplies the selected subtitle. The watch page reports MPV's actual decoded stream dimensions so a maximum preference is not mistaken for a guaranteed source resolution.
- RoxyTube isolates yt-dlp from the user's global config. An optional app-specific config can be placed at `~/.config/roxy-youtube-tv/yt-dlp.conf`; search, Channel lookup, metadata and MPV's ytdl hook share the same isolation policy.
- MPV remains embedded in the Qt video surface. The normal path uses GPU/X11 EGL with `v4l2m2m-copy`; a separate app-local DRM PRIME MPV runtime is opt-in and retries `v4l2m2m-copy`, then software decoding if the primary decoder fails.
- Automatic next-video playback follows the current result/queue order.
- Immersive playback hides surrounding UI inside the existing frameless window; the timeline and controls reappear on mouse movement near the bottom or D-pad Down, then auto-hide after one second of inactivity. It does not request OS/EWMH fullscreen.
- Back from playback returns to the Home/results page while audio playback continues; no floating video window is shown. A bordered mini-player in the Home header shows the scrolling title, progress, and remote-friendly controls; selecting its title returns to the active video without restarting it.
- The active playback queue is kept separate from newly loaded search results, so browsing or searching does not unexpectedly replace the queue currently playing. Selecting a new result deliberately replaces the active playback session.
- Home-only window controls stay pinned to the top-right corner; minimizing keeps playback running, while closing stops playback after confirmation. The app window remains frameless when restored or returned from playback fullscreen.
- Playback and window controls use compact Qt standard icons rather than relying on emoji glyph availability. The Home mini-player uses a pixel-measured scrolling title and a circular progress indicator.
- Video playback through system MPV.

## Requirements

- Python 3 with PySide6
- yt-dlp on PATH
- mpv on PATH

Run as the normal desktop user (HG680P: roxy), not root. Device deployment uses the shared interpreter at /home/Applications/.venv/bin/python.

## Run

Install the latest official yt-dlp ARM64 binary and the optional app-local Deno JavaScript runtime (as user `roxy`, no sudo):

    sh scripts/install-yt-dlp.sh
    sh scripts/install-deno.sh

Deno enables yt-dlp's YouTube JavaScript challenge solver (EJS). The installer verifies the official ARM64 release checksum and keeps Deno inside RoxyTube's app data; it does not edit the system PATH or shell profiles.

Then launch:

    sh scripts/run.sh

RoxyTube ignores `~/.config/yt-dlp/config` so external extractor arguments cannot silently constrain the app. Optional app-only yt-dlp options belong in `~/.config/roxy-youtube-tv/yt-dlp.conf`. This file is not created or modified by the installer.

The isolated DRM PRIME runtime is built and installed separately. It is never selected unless explicitly launched with:

    ROXY_ENABLE_DRMPRIME=1 sh scripts/run.sh

## Safe Area

RoxyTube uses a frameless, windowed outer rectangle for overscan compensation on X11/Openbox. Pixel margins are selected by display resolution and applied to the outer window geometry; they are not percentage padding inside the Qt layout.

Configuration file:

`~/.config/roxy-youtube-tv/window-safe-area.json`

Schema example:

```json
{
  "version": 1,
  "profiles": {
    "720x576": {
      "left": 45,
      "top": 10,
      "right": 45,
      "bottom": 10
    },
    "1920x1080": {
      "left": 0,
      "top": 0,
      "right": 0,
      "bottom": 0
    }
  }
}
```

The 720×576 values are an initial calibration candidate only and must be checked against the actual TV edges. HDMI has an independent profile. Missing or invalid profiles fall back to zero margins, except the built-in 720×576 candidate. The previous `~/.config/roxy-display/safe-area.json` percentage file is not modified or reinterpreted.

The playback expand control switches the playback UI into an immersive mode while keeping the main window windowed. Safe Area Manager integration is not yet implemented; the app currently reads its own local pixel-profile file.

## Limitations

- Public home and popular-video feeds use yt-dlp YouTube search queries because personal recommendations require account context and YouTube retired its old Trending feed endpoint. The Trending section is a public relevance-search approximation, not an official YouTube Trending ranking.
- Search depends on yt-dlp's YouTube extractor and may be affected by YouTube changes, rate limits, or access challenges.
- A selected quality is a maximum-height preference, not a guarantee the exact resolution exists.
- Thumbnail loading depends on the image URL returned by YouTube/yt-dlp.
- Startup and playback performance must be validated on the actual HG680P; this revision has not yet been device-tested.
- Remote-control behavior must be validated with the actual HG680P remote before deployment.
