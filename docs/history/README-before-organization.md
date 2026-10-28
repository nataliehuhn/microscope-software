# leica_microscope
A software package to talk to a LEICA microscope equipped with a Lumenera Camera.

To install go the repository home directory (e.g. C:\Software\leica_microscope) and execute the folloing command in the command line:

``pip install -e .``
  
("." refers to the current folder, "-e" refers to linking the installed package to this folder instead of coping the package to the python directory)

To install the Leica Microscope install:

  - the dotNet Framework from Miroscoft (dotNetFx35setup.exe)
  - the Leica Application Suite LAS (LAS 4.4.0.454.ISO)
  
To use the Lumenera Infinity Camera install:

  - the Infinity driver (Infinity.iso)

To use the Basler Camera install:

  - ???
  
To use the Hamamatsu Camera install:

  - DCAM API (DCAM-API for Windows (20.12.6136).zip) (be sure to install the version for the correct connection, e.g. USB, Firewire, DLINK)

## Fast scan on Mic3

Open `leica_microscope\Record.bat`. In the **stack** section, select
**projection_mode = optimized**, then set **projection_start_um**,
**projection_stop_um**, and **projection_time_s**. The Z offsets are relative
to the current focus (or the focus saved for each position). Choose the output
folder and positions as usual, then use **Save and Start**. Scan time must be
at least 0.25 seconds. The stage also needs space beyond both endpoints for
acceleration; a scan outside the available Z range is rejected.

This installation uses Mic3's Basler camera, `COM4` microscope connection,
stage orientation, and Mic3's Z velocity calibration from 2026-09-23.
Existing gain controls and
per-channel live-viewer exposure settings are retained. Generated recording
scripts explicitly use this checkout and the Python interpreter that launched
Record.

Optimized scans accumulate raw minimum/maximum projections and contributing
frame index maps without allocating a full image stack. Camera exposure is
chosen automatically near the frame period, so illumination may need adjusting
from the ordinary live-view settings. A preview rejects nearly black
brightfield images and images with more than 1% saturated pixels. Each scan
must meet 3% timing tolerance and at least 98% estimated exposure coverage;
up to three attempts are made before reporting failure. TIFF metadata records
the measured timing, coverage, exposure, and microscope identity.

Repeated passes at one position alternate direction and overlap TIFF writing
with acquisition. The original Z position is restored before moving to the
next XY position and when the session exits. Four TIFFs are saved per pass:
`MinProj`, `MaxProj`, `MinIndicesN`, and `MaxIndicesN`, where `N` is the number
of contributing frames. Select **default** for the previous projection method
or **off** for ordinary images/Z-stacks. Older saved checkbox configurations
are migrated when loaded.

Validation on 2026-10-23: 78 automated checks passed, including simulated
forward/reverse scans, failure recovery, generated position/mode/grid plans,
GUI configuration migration, and TIFF pixel/metadata checks. A stationary
test of Mic3's Basler acA4112-30um captured 60 full-resolution frames
(4112 x 3008) at 29.10 fps without dropped frames, using 34.1 ms exposure
(99.25% exposure duty). Camera settings were restored and Z remained unchanged.
A moving scan with a specimen has not been performed.

The pre-update files are backed up in
`C:\Software\mic3_before_fast_scan_20261023_113223`.

## Mic3 position finder

Double-click the plate map with the left mouse button to move XY to the
clicked position, leaving Z unchanged. Single clicks do not move the stage.
The red marker shows the measured position when a map is selected, a position
is stored, or a double-click move completes. Invalid targets and controller
errors are reported in the viewer.

The 1-, 6-, 12-, and 24-well maps and their source measurements were restored
from `C:\Software\leica_microscope\leica_microscope` on 2026-10-23. The maps
previously present in this checkout used Mic2's much larger coordinate scale.
Mic3's XY limits are X 0–919500 and Y 0–600750, as recorded in the older
installation's `SetLimits.py`; `microscope_config.txt` now uses those limits.
The blank map shows this full travel range. Saved experiment positions are
retained unchanged. A mounted plate's seating/alignment has not been checked.
After this correction, all 90 automated checks passed, including Qt
double-click events on each plate type and rejection of out-of-range targets.

The files replaced during this correction are backed up in
`C:\Software\mic3_before_position_fix_20261023_121926`.

## Previous projection method

`Microscope.rec_projection(...)` uses the persistent pre-accelerated projection
method. It starts the camera before the Z sweep, moves through a lead-in at the
modeled steady velocity, and selects the timestamped frame window covering the
requested Z slab. A minimum of six retained frames is enforced; short slabs are
recorded more slowly to obtain those frames.

The Mic3 velocity model is stored in
`leica_microscope/projection_velocity_model.json`, so normal experiments do not
calibrate each time. Rebuild it only after relevant Z-drive/controller changes:

```python
mic.calibratePreacceleratedProjectionModel()
```

`projection_calibration_report_20260831.md` describes the original Mic2
measurements; the calibration JSON in this installation belongs to Mic3.
  
