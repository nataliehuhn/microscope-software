# Code map

| Path | Purpose |
| --- | --- |
| `start-record.bat`, `start-live-view.bat` | Convenient entry points using this checkout |
| `leica_microscope/` | Acquisition package, GUI and hardware backends |
| `leica_microscope/microscope.py` | Leica control and recording orchestration |
| `leica_microscope/projection_motion.py` | Projection timing, frame-window and image accumulation logic |
| `leica_microscope/camera_basler.py` | Basler camera backend |
| `leica_microscope/streamer.py` | Camera streaming and shared memory |
| `leica_microscope/LiveViewer.py` | Live view, camera controls and XY position selection |
| `leica_microscope/ConfigCreator/` | Record GUI and saved-configuration templates |
| `leica_microscope/generate_record.py` | Generation of experiment scripts |
| `leica_microscope/microscope_config.txt` | Tracked, microscope-specific configuration |
| `leica_microscope/plate_data*.json` | Microscope-specific plate maps |
| `leica_microscope/projection_velocity_model.json` | Microscope-specific Z velocity calibration |
| `tests/` | Simulated regression tests |
| `tools/experiments/` | Specialist measurement and diagnostic runners |
| `docs/` | Setup, operation, history, comparison and archive index |

Runtime resources remain beside the package because the existing application
resolves them relative to its source files. Experiment runners have moved out
of the repository root; their source code is otherwise preserved. Run them as
modules from the repository root, for example:

```powershell
python -m tools.experiments.preaccelerated_projection_runner --help
```

Read each runner before executing it: these are real acquisition workflows,
not unit tests. Some write outputs relative to their own file, now beneath
`tools/experiments/`. Such generated output directories are ignored by Git.
Keep routine experiment images in a separate data directory.

The legacy `leica_microscope/delf_record.py` initializes hardware at import time.
It is retained for provenance and is not a normal entry point or a test module.
