# Adaptive FPS Format Selection Plan

## Goal

Choose a YouTube AVC/H.264 source whose frame cadence fits the active display refresh rate, without changing the source frame rate, forcing MPV video synchronization modes, or lowering resolution unnecessarily.

## Runtime behavior

1. Read the primary Qt screen refresh rate when playback starts.
2. An optional `ROXY_DISPLAY_FPS` environment override is available for displays whose X11/Qt refresh-rate reporting is inaccurate.
3. For a 50 Hz display, try AVC formats at 50 FPS first, then 25 FPS (two display refreshes per source frame), then fall back to any available AVC format.
4. For a 60 Hz display, try 60 FPS first, then 30 FPS, then fall back to any available AVC format.
5. For an unknown or uncommon refresh rate, do not impose an FPS filter; retain the AVC format baseline.
6. Keep the existing resolution preference and manual quality caps (360p/480p/720p/1080p). The default quality becomes Auto.
7. Keep MPV's existing synchronization behavior unchanged. This feature selects a source format; it does not convert or resample video frames.

## Compatibility and safety

- AVC/H.264 remains the required video codec for the HG680P playback path.
- The selector uses yt-dlp's documented numeric `fps` format filters and grouped format alternatives.
- Missing FPS metadata or unavailable preferred frame rates fall through to the next selector, then the existing AVC fallback.
- Manual resolution selections remain hard caps across every FPS alternative.
- No global yt-dlp configuration, system MPV, Xorg, display mode, Safe Area, or device configuration is changed.
- DRM PRIME remains opt-in and is not part of this change.

## Validation

- Static unit tests cover 50/25 FPS ordering, 60/30 FPS ordering, unknown refresh rates, Auto fallback, and manual resolution caps.
- CI compilation and the existing regression suite must pass.
- On HG680P, validate the actual Qt-reported refresh rate and compare 25/50/60 FPS clips at the same resolution and bitrate where possible.
- Record MPV `container-fps`, `display-fps`, `frame-drop-count`, and `decoder-frame-drop-count` over equal 30-second windows.
- Confirm a video without 50 FPS still plays through the 25 FPS or generic AVC fallback.
- Confirm manual quality selection continues to cap resolution.

## Non-goals

- Do not force all videos to 50 FPS.
- Do not transcode or duplicate/drop frames to manufacture a target FPS.
- Do not change `video-sync`, display refresh mode, kernel/driver, Xorg, Openbox, audio, Safe Area, or the MPV renderer.
