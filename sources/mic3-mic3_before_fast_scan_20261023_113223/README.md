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
  
