"""Preview or run the one-time Z velocity calibration for this microscope."""
import argparse
from datetime import datetime
import math
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leica_microscope import Microscope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", action="store_true",
        help="Run Z sweeps of up to 500 um; ensure objective/sample clearance first.",
    )
    args = parser.parse_args()
    # Velocity calibration only needs the stage; leave the live camera alone.
    mic = Microscope(no_camera=True, no_init=True)
    original_z = mic.getZPos()
    original_speed = mic.getZSpeed()
    resolution = mic.getZResolution()
    print("Microscope: {}".format(mic.getMicroscopeName()), flush=True)
    print("Starting Z: {:.4f} um ({} steps)".format(
        original_z * resolution, original_z), flush=True)
    print("Calibration sweeps: 50 to 500 um; returns to starting Z each time.",
          flush=True)
    if not args.run:
        print("Preview only. Use --run once sufficient Z clearance is confirmed.")
        return

    # Keep the existing calibration intact unless every measurement succeeds.
    model = mic.calibratePreacceleratedProjectionModel(persist=False)
    for sample in model["samples"]:
        velocity = sample["velocity_steps_s"]
        if not math.isfinite(velocity) or velocity <= 0:
            raise RuntimeError("Invalid measured velocity; model was not saved")
    if mic.getZPos() != original_z or mic.getZSpeed() != original_speed:
        raise RuntimeError(
            "The original Z position/speed was not restored; model was not saved"
        )

    path = mic.getPreacceleratedProjectionModelPath()
    if path.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = path.with_name("{}_backup_{}.json".format(path.stem, timestamp))
        shutil.copy2(path, backup)
        print("Previous calibration backed up to {}".format(backup), flush=True)
    model["path"] = str(path)
    mic.savePreacceleratedProjectionModel(model)
    reloaded = mic.loadPreacceleratedProjectionModel()
    if reloaded != model:
        raise RuntimeError("Saved calibration could not be verified")
    for sample in model["samples"]:
        print("Speed {}: {:.3f} um/s ({} samples)".format(
            sample["speed"], sample["velocity_um_s"], sample["sample_count"]),
            flush=True)
    print("Saved and verified {} calibration: {}".format(
        mic.getMicroscopeName(), path), flush=True)
    print("Original Z position and speed restored.", flush=True)


if __name__ == "__main__":
    main()
