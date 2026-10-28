# Change log

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
