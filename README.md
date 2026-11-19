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
- Video playback through system MPV.
- Quality preference: Auto, 360p, 480p, 720p (limited by formats YouTube exposes).

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

- Search depends on yt-dlp's YouTube extractor and may be affected by YouTube changes, rate limits, or access challenges.
- A selected quality is a maximum-height preference, not a guarantee the exact resolution exists.
- Thumbnail loading depends on the image URL returned by YouTube/yt-dlp.
- Startup and playback performance must be validated on the actual HG680P; this revision has not yet been device-tested.
- Remote-control behavior must be validated with the actual HG680P remote before deployment.
