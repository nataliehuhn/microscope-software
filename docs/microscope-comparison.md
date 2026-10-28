# Mic2 and Mic3: shared code and differences

Both imports descend from `fabrylab/leica_microscope` commit `efad471`.
The branches retain that history. A comparison of the source snapshots found
56 identical files after line-ending normalization. `projection_motion.py`,
`camera.py` and the serial communications helper are among the shared files.
The full comparison is in `docs/source-comparison.json`.

| Property | Mic2 | Mic3 |
| --- | --- | --- |
| Camera backend | Basler | Basler |
| Serial port | COM3 | COM4 |
| Stage Y reversed | Yes | No |
| X limits (controller units) | 0–26010000 | 0–919500 |
| Y limits (controller units) | 0–17000000 | 0–600750 |
| Projection model recorded | 2026-08-31 | 2026-09-23 |
| Record GUI settings | Config.txt (experimental wrapper also retained) | Config.txt |
| Notable additions | Timed projection experiment runners | Fast-scan refinements, corrected plate maps, double-click position finder, fluorescence group protocol |

The stage coordinates, plate maps and velocity models belong to their own
microscope. They must not be copied between branches as a generic update.
Mic3 additionally validates scan durations/exposure and anchors Z restoration
across retries; the imported Mic2 implementation has its own timing workflow.

## Consolidation decision

This migration combines the repository, history, documentation and layout.
It preserves two operational branches because their hardware settings and
control paths differ. The acquisition algorithms have not been fused or
requalified on the other rig.

For future common fixes, make a small commit and cherry-pick it to the other
branch. Run both branches' simulated tests and validate changed motion/camera
behavior on the relevant microscope before deployment. A later shared runtime
could select explicit profiles for camera, serial port, stage geometry, plate
maps and velocity model. That should follow a separate hardware validation step.
Do not merge one complete microscope branch into the other.

The desktop update carries shared fluorescence display/gain/exposure and streamer
fixes to both branches. Mic2 keeps its original map-click behaviour and timed-scan
implementation; its calibration is not replaced with Mic3 calibration.
