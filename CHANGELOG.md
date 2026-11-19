# Change log

## 2026-11-19 - Simpler Record and interruption audit

- Keep everyday recording controls visible; put presets and text editing in Options,
  and grids/sequences/cycles under Advanced settings without changing saved values.
- Validate incomplete text, imaging modes and incompatible duration plans before launch.
- Extend complete serial framing to stage and metadata commands; reject incomplete
  batches and duplicate replies without resending movement commands.
- Bring Mic2 camera recovery to Mic3 while retaining Mic3 geometry validation.
- Add original-application launchers with separate settings and monochrome icons.

## 2026-11-19 — Projection serial reply framing

- Buffer partial persistent-session serial reads until the CR terminator before
  parsing, preventing short-reply crashes and truncated numeric position values.
- Log and discard malformed frames while waiting within the existing timeout;
  preserve controller errors and bound buffering of unterminated replies.
- Added simulated regression tests for fragmented replies, malformed frames,
  controller errors, and timeouts. Targeted serial and projection tests: 61 passed.

## 2026-10-28 — Repository organization

- Imported Mic3's current working source, preserving upstream history.
- Preserved the untouched import in `archive/mic3-import-2026-10-28`.
- Added shared documentation, source comparison and archive inventories.
- Moved specialist root-level runners into `tools/experiments/` and the historical
  calibration report into `docs/history/`.
- Added root Record/live-view launchers and made package batch launchers resolve
  this checkout instead of relying on an old absolute installation path.
- Retained microscope-specific configuration, plate maps and velocity calibration.
- Added a bounded test configuration; Mic3's fluorescence test now imports its
  module by package name when run from the repository root.
- Made the fluorescence protocol resolve the adjacent package instead of an
  absolute path to the old installation; its conflicting-installation check remains.

No acquisition algorithm was merged between microscopes. Installed software,
desktop shortcuts and microscope hardware were not changed by this migration.

## 2026-10-28 — Desktop feature preservation

- Restored the fluorescence auto-contrast checkbox alongside fast scanning,
  with raw-pixel preservation and safe black-frame display.
- Retained the SetLimits utility, now reading limits from the matching config.
- Added shared fluorescence gain/exposure, group-protocol and streamer fixes to
  Mic2 without copying Mic3's acquisition algorithm or hardware calibration.
- Kept normal recording on the existing Config.txt; Mic2's experimental settings
  remain available through Record_Experimental_Copy.bat.
- Desktop deployment uses a separate installation and backs up shortcuts first.
