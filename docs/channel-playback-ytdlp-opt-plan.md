# Channel + Playback / yt-dlp Optimization Plan

## Goal

Use `feature/channel-search-playback-metadata` as the functional base and integrate the playback, yt-dlp, and DRM PRIME work selectively. Preserve the Channel experience and the existing remote-friendly, embedded-player architecture.

## Source branches

- Base: `feature/channel-search-playback-metadata`
- Playback reference: `feat/mpv-drmprime-ytdlp`
- Integration branch: `feature/channel-playback-ytdlp-opt`

The source branches have diverged. Do not merge the playback branch wholesale and do not replace the Channel branch's `app/main.py` with the playback branch's version. Port changes by responsibility and review the resulting diff.

## Non-negotiable compatibility requirements

- Preserve Channel search/cards, subscriber metadata, channel avatar, channel profile metadata, and channel navigation behavior.
- Keep MPV embedded in the Qt video surface using `--wid`; do not introduce fullscreen, DRM KMS, or direct-display takeover.
- Keep RoxyTube as the owner of D-pad/remote navigation. Do not re-enable MPV default keyboard bindings.
- Preserve Safe Area compatibility and existing window geometry behavior. Do not invent a Safe Area Manager IPC/API that is not already implemented and documented.
- Keep all runtime additions app-local; do not require system-wide package/config changes on the HG680P.
- Do not modify `main`.

## Work plan

### 1. Establish a safe baseline

- Record the base commit and inspect all relevant playback/search/metadata code paths.
- Compare the two source branches file by file.
- Keep the Channel branch's UI and channel metadata flow as the source of truth.
- Add regression tests before changing shared yt-dlp process construction.

### 2. Isolate yt-dlp configuration

- Resolve the app-local yt-dlp binary first, while retaining an explicit documented override.
- Invoke yt-dlp with an isolated config policy so `~/.config/yt-dlp/config` cannot silently force client choices or format limits on RoxyTube.
- Apply the same environment and config policy to search, channel lookup, playback metadata, and MPV's ytdl hook.
- Log the resolved executable and safe diagnostic context without exposing cookies, tokens, or private headers.

### 3. Improve YouTube format availability

- Diagnose SABR-only responses, PO Token requirements, and JavaScript challenge requirements from actual yt-dlp output.
- Provide a supported JavaScript runtime app-locally if required by the current yt-dlp release.
- Evaluate a supported PO Token provider flow; do not hardcode stale client names, scrape tokens, or claim that runtime installation alone guarantees high resolutions.
- Keep a graceful fallback when YouTube does not expose higher-resolution formats.

### 4. Preserve quality selection and playback behavior

- Retain Auto and explicit quality choices supported by the Channel branch UI; extend options only where playback and UI behavior are verified together.
- Ensure format selectors permit separate video/audio streams and compatible muxing.
- Keep MPV embedded/windowed with RoxyTube-owned remote input.
- Integrate DRM PRIME as an optional app-local MPV runtime only when its build and device compatibility checks pass.
- Use decoder fallback order based on capabilities actually reported by the runtime, including the existing `v4l2m2m-copy` path and software fallback. Never assume that listing a DRM PRIME GPU interop proves a DRM PRIME decoder exists.

### 5. Safe Area and remote regression

- Preserve the existing Qt Safe Area behavior.
- Verify video surface resizing and restoration when entering/leaving playback.
- Verify D-pad focus, quality selection, playback controls, channel cards, and channel profile navigation.
- Do not change Xorg, Openbox, kernel, drivers, Kodi, audio, or HG680P system services.

## Implemented first integration pass

The integration branch now includes the following source changes:

- The Channel branch remains the base; its channel search, cards, subscriber metadata, avatars, playback profile metadata and navigation are preserved.
- yt-dlp is resolved in this order: explicit `ROXY_YT_DLP` override, app-local binary, then PATH.
- Every direct yt-dlp process uses `--ignore-config`; if the app-specific config exists, it is loaded explicitly with `--config-locations`. The user's global yt-dlp config is not inherited.
- MPV's ytdl hook is given the same yt-dlp directory through PATH and receives the isolated config options.
- Quality choices include 1080p, with quality fallback after decoder fallback.
- Normal MPV playback uses GPU/X11 EGL and `v4l2m2m-copy` by default. The optional isolated runtime requests its V4L2 DRM PRIME decoder first, then retries `v4l2m2m-copy` and software decoding.
- The DRM PRIME build, checksum-verified installer, patch compatibility check, and ARM64 Actions workflow are present on this branch.
- Static tests protect Channel features, yt-dlp config isolation, embedded MPV, decoder fallback, remote input ownership, and Qt Safe Area boundaries.

This is source/CI integration only. It is not yet evidence that the DRM PRIME runtime builds successfully or that the HG680P can use zero-copy frames. The JavaScript runtime and PO Token provider needed to resolve YouTube SABR/format availability remain a separate diagnostic/integration task; the current branch isolates the known global client override but does not claim that this alone guarantees 720p/1080p formats.

## Validation checklist

- [ ] Python syntax checks pass.
- [ ] Channel search and channel cards remain functional.
- [ ] Subscriber counts and channel avatars remain intact.
- [ ] Playback metadata and channel profile button remain functional.
- [ ] yt-dlp app-local binary is selected consistently by RoxyTube and MPV.
- [ ] User-global yt-dlp config does not override RoxyTube's intended settings.
- [ ] Sample video format listing exposes available formats accurately.
- [ ] Auto and explicit quality selectors map to the intended yt-dlp format selectors.
- [ ] MPV remains embedded with `--wid`; no fullscreen/KMS takeover.
- [ ] Remote/D-pad navigation remains owned by RoxyTube.
- [ ] Safe Area behavior is not regressed.
- [ ] DRM PRIME runtime is optional and has a tested fallback path.
- [ ] CI results are checked before declaring the branch ready.

## Current diagnostic evidence

On the HG680P, yt-dlp `2026.11.23` listed only format 18 (360p) for the Big Buck Bunny sample. The verbose output showed:

- Global config forced `youtube:player_client=android,web`.
- Android and web HTTPS formats were skipped because their URLs were missing under SABR.
- No JavaScript runtime was available.
- No PO Token provider was available.

This indicates that the immediate 360p limitation occurs during YouTube format extraction, before MPV chooses a stream. The exact remedy must be verified against the current yt-dlp diagnostics and supported provider/runtime documentation.

## Delivery approach

Work in small commits on this branch. Do not merge into `main` or change the HG680P installation until the user reviews the completed branch and explicitly approves deployment.
