# RoxyTube UI Polish Plan

**Status:** Approved design; implementation pending  
**Target branch:** `feature/plasmatube-style-ui`  
**Scope:** Visual-only refinements to the home/video-card UI, RoxyTube header, and playback channel label.

## Approved visual specification

### Home / video thumbnail cards

- Preserve the main thumbnail card border as it appeared before the recent border-removal styling change.
- Remove the black background behind the video title, channel name, and view-count text only.
- Keep the video duration badge exactly as it was before the recent styling change; do not alter its background, border, placement, or typography.
- Keep the video title at its current size and retain the existing focus indication (yellow title on D-pad focus).
- Increase the channel-name text slightly and make it bold. It must remain smaller than the video title.
- Increase the view-count text and make it bold. It must remain slightly smaller than the channel-name text.

### Playback metadata

- Increase the playback channel-name text slightly and make it bold.
- Do not change playback view-count styling.
- Do not change playback duration or actual-resolution styling.

### RoxyTube header

- Increase the RoxyTube header text size.
- Enlarge the RoxyTube logo proportionally.
- Keep the header and logo in their current positions; do not shift the surrounding layout.

## Visual hierarchy

For thumbnail-card text, preserve this relative hierarchy:

1. Video title — largest.
2. Channel name — slightly enlarged and bold.
3. View count — enlarged and bold, but smaller than the channel name.

## Strict implementation boundaries

- Make only the targeted visual/style changes described above.
- Do not change playback logic, yt-dlp metadata retrieval, queue behavior, D-pad navigation, search, pagination, focus behavior, or other working features.
- Do not change the duration badge.
- Do not remove the main thumbnail border.
- Preserve the current header/logo placement.
- Work only on `feature/plasmatube-style-ui`.
- Do not modify or merge into `main` without explicit approval.

## Validation

After implementation, inspect the diff to confirm it is limited to the intended UI styling. Then the user will pull the development branch and test the appearance directly on the HG680P. Do not claim device validation until the user confirms the test result.
