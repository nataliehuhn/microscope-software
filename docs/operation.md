# Operate Mic3

## Routine recording

1. Start `start-live-view.bat` in the verified Python environment.
2. Check focus, illumination and saved XY positions on the actual mounted plate.
3. Open `start-record.bat`, choose output folder, positions and imaging settings.
4. In the stack section choose `projection_mode`: `off` for ordinary images or
   Z-stacks, `default` for the previous projection method, or `optimized` for
   the timed projection workflow.
5. For optimized mode enter `projection_start_um`, `projection_stop_um` and
   `projection_time_s`, then use **Save and Start** when ready for acquisition.

Z offsets are relative to current focus or the focus saved with a position.
Generated scripts, normal entry points and tests serve different purposes:
starting a recording or an experiment runner can move the microscope.

## Mic3 features

Optimized scans accept durations of at least 0.25 seconds. Z travel also needs
room beyond the requested endpoints for acceleration. Scans check timing within
3% and estimated exposure coverage of at least 98%, retrying up to three times.
They save raw minimum/maximum projections and contributing frame-index maps.
TIFF metadata records scan timing, exposure, coverage and microscope identity.
Exposure is selected near the frame period; review illumination for that exposure.
The starting Z is restored across repeated scans and on exit.

In the position finder, a left double-click moves XY while preserving Z.
A single click does not move the stage. Mic3's corrected plate maps use its
smaller coordinate range; physical plate seating still needs checking.

`leica_microscope/MigAssay_FluoGroups.py` is a specialist fluorescence protocol.
Run it from this checkout with `python -m leica_microscope.MigAssay_FluoGroups`.
It resolves the adjacent microscope package and rejects a conflicting imported
installation. Review its experiment paths and condition settings first;
`--dry-run` checks position groups without connecting to hardware. Keep the
script in the package when using this checkout. Its tests use simulated hardware.

The imported notes report a stationary camera test at 29.10 fps (60 frames,
4112 × 3008, 34.1 ms exposure). A moving specimen scan was not performed as part
of this repository migration.

## Calibration and troubleshooting

Keep the matching velocity model; routine acquisition does not need a new
calibration. Recalibration drives the Z stage and belongs to a separate operator
procedure after relevant controller/drive changes. The historical calibration
report is in [docs/history](history/projection_calibration_report_20260831.md).

For import errors, check Python's executable and the package location as in
[setup](setup.md). For wrong microscope identity, port, stage scale or plate map,
stop and check branch/configuration before further motion. For an acquisition
failure, retain the generated script and error output with the experiment data.

[Original detailed notes](history/README-before-organization.md) preserve the
pre-migration operating and calibration descriptions. Paths in those notes
describe the original installations and may predate this folder organization.

## Legacy features retained in the desktop version

The histogram's **Auto-contrast (fluorescence)** checkbox is available alongside
per-channel exposure memory and gain controls. Auto-contrast affects the display
only, leaving raw images unchanged. Black frames remain black without division
by zero. Ordinary single images, Z-stacks, the previous projection mode, grids,
positions and repetitions remain available. Optimized fast scanning is opt-in.

`SetLimits.bat` applies this branch's configured XY limits. Console, configuration
editing and the existing reset utility are also retained. Reset remains a
maintenance operation, with the original process-reset behaviour.
