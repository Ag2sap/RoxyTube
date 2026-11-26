# RoxyTube H.264 / V4L2-M2M Playback Plan

## Baseline

This work is based on `feature/channel-playback-ytdlp-opt`. Preserve its channel playback, app-managed yt-dlp/Deno setup, embedded MPV window, quality selector, and Safe Area behavior.

## Target

Use YouTube AVC/H.264 streams on the HG680P so MPV can use the Amlogic `meson-vdec` V4L2 M2M decoder. Keep the existing MPV + Qt embedded-window architecture; do not add a renderer or alter kernel, drivers, Xorg, Openbox, or audio configuration.

## Current code changes

- Filter Auto, 360p, 480p, 720p, and 1080p format choices to AVC streams (`vcodec^=avc1`).
- Keep the existing resolution choices and resolution caps for explicit quality selections.
- Request MPV hardware decoding for H.264 using the existing `v4l2m2m-copy` default and `--hwdec-codecs=h264`.
- Wait for the previous MPV process to exit before starting a replacement. This prevents overlapping MPV processes from competing for the embedded video surface and IPC socket during quality changes.
- Keep the existing EGL/GPU output, ALSA route, Qt child-window embedding, and Safe Area ownership unchanged.

## Validation on HG680P

1. Pull this branch and run Python syntax compilation.
2. Confirm the running MPV binary accepts `--hwdec-codecs=h264`.
3. Play a YouTube video that offers AVC at 1080p. Confirm the displayed stream resolution reaches 1920x1080 when available.
4. Inspect MPV's video decoder log/property and confirm H.264 uses `v4l2m2m-copy` / `meson-vdec` and produces frames.
5. Switch through Auto, 360p, 480p, 720p, and 1080p while playing. Confirm each selection restarts only one MPV process and the actual stream resolution changes within the selected cap.
6. Confirm audio, D-pad controls, embedded window geometry, fullscreen/restore, and Safe Area behavior remain intact.

## Known limits

- `v4l2m2m-copy` is a hardware decode copy-back path, not zero-copy DRM PRIME.
- Earlier tests showed a YouTube H.264 stream could decode through `meson-vdec`, while local MP4 tests stalled. This branch does not claim to fix every V4L2 input/container path.
- Do not change the kernel or device drivers as part of this work. If hardware decoding still fails, capture MPV logs and validate the selected stream and decoder path before changing system components.
