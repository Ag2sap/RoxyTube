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
- Quality preference: Auto, 360p, 480p, or 720p (limited by formats YouTube exposes). A quality change restarts the stream at the current playback position and reapplies the selected subtitle. The watch page reports MPV's actual decoded stream dimensions so a 720p maximum preference is not mistaken for a guaranteed 720p source.
- Automatic next-video playback follows the current result/queue order.
- Playback Safe Area hides surrounding playback UI; timeline and controls reappear on mouse movement near the bottom or D-pad Down, then auto-hide after one second of inactivity. The top-level window position and size are owned by the external Safe Area Manager Controller.
- Back from playback returns to the Home/results page while audio playback continues; no floating video window is shown. A bordered mini-player in the Home header shows the scrolling title, progress, and remote-friendly controls; selecting its title returns to the active video without restarting it.
- The active playback queue is kept separate from newly loaded search results, so browsing or searching does not unexpectedly replace the queue currently playing. Selecting a new result deliberately replaces the active playback session.
- Home-only window controls stay pinned to the top-right corner; minimizing keeps playback running, while closing stops playback after confirmation. The app window remains frameless when restored or returned from playback Safe Area.
- Playback and window controls use compact Qt standard icons rather than relying on emoji glyph availability. The Home mini-player uses a pixel-measured scrolling title and a circular progress indicator.
- Video playback through system MPV.

## Requirements

- Python 3 with PySide6
- yt-dlp on PATH
- mpv on PATH

Run as the normal desktop user (HG680P: roxy), not root. Device deployment uses the shared interpreter at /home/Applications/.venv/bin/python.

## Run

    sh scripts/run.sh

## Safe Area

RoxyTube reads the active profile from the Safe Area Manager configuration:

    /home/Applications/Safe-Area-Manager-With-Controller/config/profiles.json

Override this path with the `SAFE_AREA_CONFIG` environment variable. The same active profile drives RoxyTube's internal content margins and the external Openbox Window Geometry Controller. When the Manager profile is disabled, RoxyTube uses zero internal margins.

The legacy `~/.config/roxy-display/safe-area.json` is used only when the Manager profile file is absent, preserving standalone compatibility. If the Manager file exists but is invalid, RoxyTube uses the safe 5% default rather than silently preferring stale legacy settings.

The external Safe Area Controller owns the top-level window rectangle. Playback Safe Area only hides or reveals playback chrome; it does not resize or maximize the application window itself. This keeps Manager and Controller as the single source of truth for window geometry.

## Limitations

- Public home and popular-video feeds use yt-dlp YouTube search queries because personal recommendations require account context and YouTube retired its old Trending feed endpoint. The Trending section is a public relevance-search approximation, not an official YouTube Trending ranking.
- Search depends on yt-dlp's YouTube extractor and may be affected by YouTube changes, rate limits, or access challenges.
- A selected quality is a maximum-height preference, not a guarantee the exact resolution exists.
- Thumbnail loading depends on the image URL returned by YouTube/yt-dlp.
- Startup and playback performance must be validated on the actual HG680P; this revision has not yet been device-tested.
- Remote-control behavior must be validated with the actual HG680P remote before deployment.
