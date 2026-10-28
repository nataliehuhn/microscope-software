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

## Projection recording

`Microscope.rec_projection(...)` uses the persistent pre-accelerated projection
method. It starts the camera before the Z sweep, moves through a lead-in at the
modeled steady velocity, and selects the timestamped frame window covering the
requested Z slab. A minimum of six retained frames is enforced; short slabs are
recorded more slowly to obtain those frames.

The Mic2 velocity model is stored in
`leica_microscope/projection_velocity_model.json`, so normal experiments do not
calibrate each time. Rebuild it only after relevant Z-drive/controller changes:

```python
mic.calibratePreacceleratedProjectionModel()
```

See `projection_calibration_report_20260831.md` for the measurements and
validation results.

### Opt-in timed continuous projection

`Microscope.recordTimedContinuousProjection(start_um, stop_um, seconds)`
records a min/max pair with no requested slice spacing. The offsets are
relative to the current Z position. It selects a near-full-duty camera exposure
without lowering the full-resolution readout rate, pre-accelerates the Z stage,
and uses camera timestamps plus polled stage positions to include every frame
whose exposure intersects the requested slab. It returns the min image, max
image, and detailed Z coverage/timing diagnostics. Camera exposure, stage speed,
and starting Z are restored after each call. The Basler-only record-GUI wrapper
also verifies the requested scan time and saves raw projection images.

`timed_projection_experiment.py` runs the requested INT 4 / AP 7 series at
−100 to +100 µm in 1, 2, 4, 8, and 16 seconds. It saves min/max TIFFs under
`INT_4_AP_7/min_projections` and `INT_4_AP_7/max_projections` and writes a
per-run JSON manifest. The runner checks illumination before any motion and
restores the original light, aperture, shutter, exposure, speed, and Z settings.

`timed_projection_600um_experiment.py` is the validated ±300 µm variant. It
measures the actual time between Z crossings and retries any duration outside
±3% of the request. Raw projections stay in memory; after all scans pass, it
uses one shared percentile-based display window and writes only enhanced
min/max TIFFs to a new `INT_4_AP_7/600um_<timestamp>` folder. The run manifest
records all attempts, the contrast mapping, and restored hardware state.

### Record GUI in this isolated copy

Launch `leica_microscope/Record_Experimental_Copy.bat` to use the GUI and
generated recording scripts from this copy. It keeps separate settings in
`%APPDATA%/Microscope/Config_Experimental_Copy.txt`; the original
`Record.bat` and installed code remain untouched. Under **stack**, choose
**off** (the default), **default** (the old slice-width projection), or
**optimized** (distance and time). Off shows the ordinary Z-stack slice
controls; default shows those same controls for the old projection; optimized
shows Z start/stop offsets in µm and scan time in seconds. Optimized verifies
the actual Z-crossing time to within 3% and retries a miss. It saves the
unmodified `MinProj`, `MaxProj`, `MinIndices*`, and `MaxIndices*` TIFFs with the
same naming convention as the old recorder. Contrast enhancement is a separate
post-processing task and is never performed by the record GUI. Older saved
configs with projection enabled migrate to the old/default method rather than
silently changing their scan geometry.

For repeated optimized projections, the generated script alternates upward and
downward passes at a fixed position, rather than returning to the middle after
each pass. The Z drive uses its maximum commanded speed for the initial lead-in
and the final return, and avoids redundant speed/position commands when a pass
already starts at the previous pass's endpoint. Completed TIFFs are written by
one background worker while acquisition continues; the script waits for all
writes before exiting and restores the reference Z even if acquisition fails.
With multiple modes, each mode change gets a new camera/illumination preflight.
Before moving to another XY position, the script restores that position's
reference Z and starts a new alternating sequence. Repetition interval remains
a minimum start-to-start delay, not a guaranteed cycle time. New
`phase_seconds` entries in optimized TIFF metadata report setup, positioning,
camera startup and sweep timings for a live performance check; the final
return-to-center time is printed by the recording script.
  
