# Operate Mic2

## Routine recording

1. Start `start-live-view.bat` in the verified Python environment.
2. Check focus, illumination and saved XY positions on the actual mounted plate.
3. Open `start-record.bat`, choose output folder, positions and imaging settings.
4. In the stack section choose `projection_mode`: `off` for ordinary images or
   Z-stacks, `default` for the previous projection method, or `optimized` for
   the timed projection workflow.
5. For optimized mode enter `projection_start_um`, `projection_stop_um` and
   `projection_time_s`, then use **Save and Start** when ready for acquisition.

For a long recording at one position, click **Single position, 24 h** in Record.
It uses the current microscope position and keeps your selected mode and Z scan
settings. Adjust `minimum_duration_hours` in **repetition** for another duration.
Use one mode and a 1 x 1 grid.
Set `repetition_time_delta` for the minimum interval between starts. A positive
duration uses elapsed time rather than `repetition_count`, and the final scan
can finish shortly after the requested duration. Leave the positions file empty
to stay at the current position, or select a file with exactly one saved
position. Set the duration back to `0` to use the traditional repetition count.
When setting up a 24-hour experiment, check the displayed duration before
pressing **Save and Start**.

Z offsets are relative to current focus or the focus saved with a position.
Generated scripts, normal entry points and tests serve different purposes:
starting a recording or an experiment runner can move the microscope.

## Mic2 features

The Record GUI supports opt-in timed continuous projection. The imported
`recordTimedContinuousProjection` method records minimum/maximum projections
over requested Z offsets and duration using the Basler camera. Camera exposure,
stage speed and starting Z are restored by the acquisition code.

Optimized scans accept durations of at least 0.25 seconds. Z travel also needs
room beyond the requested endpoints for acceleration. Scans check timing within
3% and estimated exposure coverage of at least 98%, retrying up to three times.
They save raw minimum/maximum projections and contributing frame-index maps.
TIFF metadata records scan timing, exposure, coverage and microscope identity.
Exposure is selected near the frame period; review illumination for that exposure.
If the preview or a completed projection has more than 1% saturated pixels,
Record prints a warning and keeps saving images. The warning and saturation
fraction are also stored in TIFF metadata. Saturated pixels cannot be recovered;
adjust illumination or gain before starting when quantitative intensities matter.
The starting Z is restored across repeated scans and on exit.

`Record.bat` uses the existing `Config.txt` settings, preserving the regular
desktop workflow. `Record_Experimental_Copy.bat` still uses the separate
`Config_Experimental_Copy.txt` settings when explicitly chosen.

Specialist timed-projection workflows live in `tools/experiments/`, including
`timed_projection_experiment.py`, `timed_projection_600um_experiment.py`,
`three_position_fast_projection_run.py` and `contrast_enhance_projections.py`.
The original notes report validation of the ±300 µm variant; that experiment
was not repeated during this migration. Read the runner's parameters and output
paths before executing it. Their `INT_4_AP_7` data folder now resolves beneath
`tools/experiments/`.

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

The fluorescence group protocol (`MigAssay_FluoGroups.py`), Basler gain control,
per-channel exposure memory and streamer startup fixes from the fluorescence
installation are included. Mic2 retains its own Z model and stage coordinates.
