# Set up Mic3

## Use the correct branch

Create a separate checkout; keep the known working installation until the new
checkout has been validated on this microscope.

```powershell
git clone --branch mic3 https://github.com/nataliehuhn/microscope-software.git C:\Software\microscope-software-mic3
cd C:\Software\microscope-software-mic3
git status --short --branch
```

This is a private repository; Git authentication is needed to clone it.

## Python and drivers

Use the microscope's working Python environment, with its existing Leica
controller connection and Basler camera drivers. The launchers call `python`
from PATH. Confirm the interpreter before starting acquisition:

```powershell
python -c "import sys; print(sys.executable)"
python -c "import leica_microscope; print(leica_microscope.__file__)"
python -m pip check
```

The package location printed from the checkout should be this checkout.
`docs/environment-observed.txt` records package versions observed on the Mic3
migration PC; it is a reference, not a verified fresh-install recipe or an
inventory of Mic2's installed environment. Camera driver installation and
operation on a new PC have not been tested here.

The supplied launchers prepend this checkout to PYTHONPATH. Editable installation
is therefore unnecessary for these launchers. The inherited `setup.py` has
incomplete dependency declarations and creates/replaces generic desktop
shortcuts on Windows. Review those effects before using `pip install -e .`.

## Configuration and first use

Review these branch-specific files together:

- `leica_microscope/microscope_config.txt`: microscope name, Basler backend,
  serial port, stage direction and limits.
- `leica_microscope/plate_data*.json`: plate coordinates.
- `leica_microscope/projection_velocity_model.json`: model identity and date.

The imported configuration is tracked intentionally in this private repository.
Commit reviewed calibration changes only on the matching microscope branch.
See [the comparison table](microscope-comparison.md) for expected values.

With acquisition stopped, activate the known working environment and open
`start-live-view.bat`. Confirm image orientation, position readout and plate
alignment before relying on saved positions. Open `start-record.bat` for the
Record GUI. The settings file is `%APPDATA%\Microscope\Config.txt`.
Select an experiment output folder outside the checkout.

Validate any changed camera settings or motion with an operator before using
the checkout for routine experiments. To roll back, close this checkout's
programs and launch the preserved original installation with its own shortcut.
Desktop shortcuts may be repointed during deployment. Their original links and
settings are backed up before replacement; original installed folders are retained.
