# Roxy YouTube TV

A lightweight YouTube TV-style frontend for HG680P / Armbian Noble (ARM64).

**Status: MVP scaffold.** This is a standalone app, separate from LauncherTV. It does not modify Xorg, Openbox, kernel, or the existing LauncherTV installation.

## MVP features

- TV-oriented dark interface with keyboard / D-pad navigation.
- Search public YouTube videos using `yt-dlp`.
- Display title, channel, duration and asynchronously loaded thumbnails when provided by yt-dlp.
- Play selected video using the system `mpv` executable.
- Quality preference: Auto, 360p, 480p, 720p (limited by formats YouTube exposes).
- Shared Safe Area configuration at `~/.config/roxy-display/safe-area.json`.

## Requirements

- Python 3
- PySide6 (Qt Widgets)
- `yt-dlp` on PATH
- `mpv` on PATH

Run as the normal desktop user (HG680P: `roxy`). Do not run as root.

## Run

```bash
python3 app/main.py
```

or:

```bash
sh scripts/run.sh
```

Set `ROXY_YT_DLP` or `ROXY_MPV` to override executable paths if needed.

## Safe Area

The app reads `~/.config/roxy-display/safe-area.json`. If missing, defaults are used. Margins are percentages of the app window and affect the interface only; they do not change Xorg output geometry or MPV video scaling.

Example:

```json
{
  "aspect_ratio": "4:3",
  "margin_left": 5,
  "margin_right": 5,
  "margin_top": 5,
  "margin_bottom": 5
}
```

## Limitations

- Search depends on yt-dlp's YouTube extractor and may be affected by YouTube changes, rate limits, or access challenges.
- A selected quality is a maximum-height preference, not a guarantee the exact resolution exists.
- This is an independent frontend, not the official YouTube app. No account sign-in, DRM circumvention, or private-video access is provided.
- Thumbnail loading depends on the image URL returned by YouTube/yt-dlp; some results may remain text-only.\n- Remote-control behavior is keyboard-based and should be validated on the actual HG680P remote before deployment.
