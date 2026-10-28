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

Z offsets are relative to current focus or the focus saved with a position.
Generated scripts, normal entry points and tests serve different purposes:
starting a recording or an experiment runner can move the microscope.

## Mic2 features

The Record GUI supports opt-in timed continuous projection. The imported
`recordTimedContinuousProjection` method records minimum/maximum projections
over requested Z offsets and duration using the Basler camera. Camera exposure,
stage speed and starting Z are restored by the acquisition code.

`Record.bat` now launches this checkout with the separate
`Config_Experimental_Copy.txt` settings. The older
`Record_Experimental_Copy.bat` name remains as a compatibility wrapper.

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
