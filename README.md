# Roxy YouTube TV

A lightweight YouTube TV-style frontend for HG680P / Armbian Noble (ARM64).

**Status: UI revision for device testing.** This is a standalone app, separate from LauncherTV. It does not modify Xorg, Openbox, kernel, or the existing LauncherTV installation.

## Interface

- Single-window TV interface; no popup keyboard dialog.
- Compact 4:3-oriented window with responsive Safe Area margins.
- Search bar with adjacent keyboard and search controls.
- Integrated on-screen keyboard slides down below the search row and pushes the results area down; SELESAI or Back slides it away.
- Android-TV-inspired keyboard rows with letters, digits, persistent CAPS, one-shot SHIFT, symbol page, comma, period, punctuation, space, backspace, and clear.
- Search results shown as large 16:9 thumbnail cards in a two-column grid on 4:3 layouts, with title, channel/artist and duration.
- D-pad navigation across search controls, keyboard and thumbnail cards.
- PlasmaTube-inspired watch page with embedded MPV, a timeline directly below the video, 10-second rewind/forward, playback controls, and a lower queue/description panel.
- D-pad navigation across the timeline, playback controls, queue items, and scrollable description.
- Subtitle choices are enumerated after playback starts; the selected external track is applied to the active MPV session, preferring WebVTT when available.
- Quality preference: Auto, 360p, 480p, 720p (limited by formats YouTube exposes). A quality change restarts the stream at the current playback position and reapplies the selected subtitle.
- Automatic next-video playback follows the current result/queue order.
- Fullscreen playback hides surrounding UI; the timeline and controls reappear on mouse movement near the bottom or D-pad Down, then auto-hide after one second of inactivity.
- Back from playback returns to the Home/results page while audio playback continues; no floating video window is shown. A bordered mini-player in the Home header shows the scrolling title, progress, and remote-friendly controls; selecting its title returns to the active video without restarting it.
- The active playback queue is kept separate from newly loaded search results, so browsing or searching does not unexpectedly replace the queue currently playing. Selecting a new result deliberately replaces the active playback session.
- Home-only window controls minimize the application without stopping playback or close the application and stop playback after confirmation.
- Playback and window controls use Qt standard icons rather than relying on emoji glyph availability.
- Video playback through system MPV.

## Requirements

- Python 3 with PySide6
- yt-dlp on PATH
- mpv on PATH

Run as the normal desktop user (HG680P: roxy), not root. Device deployment uses the shared interpreter at /home/Applications/.venv/bin/python.

## Run

    sh scripts/run.sh

## Safe Area

The app reads ~/.config/roxy-display/safe-area.json. If missing, defaults are used. Margins are percentages of the app window and affect the interface only; they do not change Xorg output geometry or MPV video scaling.

Example:

    {
      "aspect_ratio": "4:3",
      "margin_left": 5,
      "margin_right": 5,
      "margin_top": 5,
      "margin_bottom": 5
    }

## Limitations

- Public home and popular-video feeds use yt-dlp YouTube search queries because personal recommendations require account context and YouTube retired its old Trending feed endpoint. The Trending section is a public relevance-search approximation, not an official YouTube Trending ranking.
- Search depends on yt-dlp's YouTube extractor and may be affected by YouTube changes, rate limits, or access challenges.
- A selected quality is a maximum-height preference, not a guarantee the exact resolution exists.
- Thumbnail loading depends on the image URL returned by YouTube/yt-dlp.
- Startup and playback performance must be validated on the actual HG680P; this revision has not yet been device-tested.
- Remote-control behavior must be validated with the actual HG680P remote before deployment.
