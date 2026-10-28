# Migration validation — 2026-10-28

- Branch: `mic2`.
- Command: `python -m pytest -q` from the checkout root.
- Result: **39 passed**, 2 warnings, no failures.
- Environment: existing Python 3.8.3 environment on the Mic3 migration PC.
- Scope: simulated regression checks; no microscope motion or acquisition was invoked.

Existing warnings include legacy library deprecations and a NumPy binary-size
warning. The Mic3 GUI checks also report numeric-to-integer coercion warnings.
The preserved environment should be reviewed separately before dependency upgrades.

The selected Mic2 files were re-enumerated and hashed against the completed
transfer share. All matched the import. All 868 published archive source files
across 12 snapshots match their manifests byte for byte. Local archive creation
also checked ZIP CRCs and recorded SHA-256 hashes.

Moved experiment runners match their original source after line-ending
normalization. Current documentation's relative links resolve locally.
The launchers were inspected but not run, because opening them starts hardware
software. No new physical camera, stage or plate-alignment validation was performed.

Desktop update: **80 tests passed** in the local validation environment.
This includes the restored auto-contrast display, black frames, raw-image
preservation, fluorescence gain/exposure and configured-limit regressions.
Physical operation on Mic2 was not tested by this local suite.
