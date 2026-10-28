# Development and validation

Work on the branch for the target microscope. Keep camera/stage changes small
and reviewable. Shared fixes can be cherry-picked to the other branch after
review; see [consolidation notes](microscope-comparison.md).

Run the selected simulated suite from the checkout root:

```powershell
python -m pytest -q
```

`pytest.ini` limits collection to the maintained tests. Hardware experiment
runners in `tools/experiments/` are not tests. Do not import arbitrary legacy
scripts to check whether they work: some initialize hardware at import time.

The migration validation results are recorded in `docs/validation.md`.
These tests cover logic with simulated cameras/microscopes; they do not certify
the camera driver, serial connection, stage clearance or plate alignment.

Use a separate checkout when comparing Mic2 and Mic3, and close hardware
programs before changing checked-out code. Keep images and runtime memory maps
outside commits. Preserve the source license and each rig's calibration identity.
