"""Single-image fluorescence time course, with brightfield at start and end.

Edit the settings below, then run: python MigAssay_FluoGroups.py
Use --dry-run to check the position groups without connecting to the microscope.
Position numbers are the non-comment rows in pos.txt, starting at 1.
The file order is preserved: positions already grouped by condition stay grouped.
"""
import argparse
from datetime import datetime
import importlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import time

import numpy as np


# --------------------------- EDIT THESE SETTINGS ---------------------------
SOFTWARE_FOLDER = Path(r"C:\Software\codex-microscope-software\leica_microscope")
EXPERIMENT_FOLDER = Path(r"D:\EDIT_ME\experiment")
POSITIONS_FILE = EXPERIMENT_FOLDER / "pos.txt"
OUTPUT_FOLDER = EXPERIMENT_FOLDER / "data_fluorescence"

FLUORESCENCE_CHANNEL = "FLUO1"  # Same channel for every condition: FLUO1 .. FLUO6.
FLUORESCENCE_REPETITIONS = 10   # Placeholder: number of full passes over ALL positions.
INTERVAL_SECONDS = 60.0        # Minimum interval between the starts of fluorescence passes.
SETTLE_SECONDS = 0.5           # Wait after moving and applying camera settings.

# Placeholder values: replace with settings suitable for your samples.
# range(1, 6) means positions 1, 2, 3, 4, 5. The stop number is excluded.
# Add more conditions by copying a block. Assign EVERY position exactly once.
CONDITIONS = [
    dict(name="condition_A", positions=range(1, 6), exposure_ms=20.0, gain_db=0.0),
    dict(name="condition_B", positions=range(6, 11), exposure_ms=100.0, gain_db=6.0),
]

BRIGHTFIELD_MODE = "BF"         # Use "POL" here if you want the example's polarized mode.
BRIGHTFIELD = dict(exposure_ms=3.0, gain_db=0.0, lamp_intensity=None)
# lamp_intensity: optional microscope lamp value, 0..255; None leaves it unchanged.
# Fluorescence groups above vary camera exposure/gain. An external fluorescence
# light source's power is not controlled by this script.
# --------------------------------------------------------------------------


def load_positions(path):
    positions = np.loadtxt(path, ndmin=2)
    if positions.size == 0 or positions.shape[1] != 3:
        raise ValueError("The positions file must contain three columns: X Y Z")
    if not np.all(np.isfinite(positions)) or not np.all(positions == np.round(positions)):
        raise ValueError("Positions must be finite integer stage coordinates")
    return positions.astype(np.int64)


def condition_map(conditions, count):
    """Map original one-based position numbers to their condition settings."""
    assignments = {}
    names = set()
    for condition in conditions:
        name = condition["name"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or name in names:
            raise ValueError("Use a unique condition name containing letters, digits, _ or -")
        names.add(name)
        numbers = list(condition["positions"])
        if not numbers:
            raise ValueError("{} has no positions".format(name))
        for number in numbers:
            if isinstance(number, bool) or not isinstance(number, (int, np.integer)) or not 1 <= number <= count:
                raise ValueError("Invalid position {!r} in {}; the file has {} rows".format(number, name, count))
            if number in assignments:
                raise ValueError("Position {} belongs to more than one group".format(number))
            assignments[int(number)] = condition
    missing = sorted(set(range(1, count + 1)) - set(assignments))
    if missing:
        raise ValueError("Assign these positions to a condition: {}".format(missing))
    return assignments


def validate_settings(settings):
    for key in ("exposure_ms", "gain_db"):
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("{} must be a finite number".format(key))
        if value < 0 or (key == "exposure_ms" and value == 0):
            raise ValueError("{} is outside its valid range".format(key))
    intensity = settings.get("lamp_intensity")
    if intensity is not None and (isinstance(intensity, bool) or not isinstance(intensity, int) or not 0 <= intensity <= 255):
        raise ValueError("lamp_intensity must be None or an integer from 0 to 255")


def load_microscope_class():
    """Use the updated checkout, even when this script is copied elsewhere."""
    expected = SOFTWARE_FOLDER.resolve()
    if not (expected / "microscope.py").is_file():
        raise FileNotFoundError("Microscope software not found at {}".format(expected))
    sys.path.insert(0, str(expected.parent))
    module = importlib.import_module("leica_microscope.microscope")
    backend = importlib.import_module("leica_microscope.camera_basler")
    for loaded in (module, backend):
        if Path(loaded.__file__).resolve().parent != expected:
            raise RuntimeError("Wrong software copy loaded: {}".format(loaded.__file__))
    print("Using microscope software:", expected, flush=True)
    return module.Microscope


def verify_camera_ranges(mic, conditions, brightfield):
    if mic.config.get("camera") != "basler":
        raise RuntimeError("This protocol uses the Basler camera's gain in dB")
    minimum, maximum = mic.cam.get_gain_range()
    exposure_min = mic.cam.camera.ExposureTime.Min / 1000.0
    exposure_max = mic.cam.camera.ExposureTime.Max / 1000.0
    for settings in list(conditions) + [brightfield]:
        if not minimum <= settings["gain_db"] <= maximum:
            raise ValueError("Gain {} dB is outside this camera's {}..{} dB range".format(settings["gain_db"], minimum, maximum))
        if not exposure_min <= settings["exposure_ms"] <= exposure_max:
            raise ValueError("Exposure {} ms is outside this camera's {}..{} ms range".format(settings["exposure_ms"], exposure_min, exposure_max))


def apply_camera_settings(mic, settings):
    # Manual settings must stay fixed for a concentration comparison.
    mic.cam.camera.ExposureAuto.Value = "Off"
    mic.setProperties(exposure=settings["exposure_ms"], gain=settings["gain_db"],
                      intensity=settings.get("lamp_intensity"))
    actual_gain = mic.cam.gain()
    actual_exposure = mic.cam.exposure()
    # This Basler rounds gain to 0.1 dB increments (e.g. 6.25 -> 6.3 dB).
    if actual_gain is None or not math.isfinite(actual_gain) or abs(actual_gain - settings["gain_db"]) > 0.11:
        raise RuntimeError("Gain was not applied: requested {} dB, camera reports {!r}".format(settings["gain_db"], actual_gain))
    if mic.cam.camera.GainAuto.Value != "Off":
        raise RuntimeError("Automatic gain is still enabled; the requested gain is not fixed")
    if not math.isclose(actual_exposure, settings["exposure_ms"], rel_tol=0.01, abs_tol=0.01):
        raise RuntimeError("Exposure was not applied: requested {} ms, camera reports {}".format(settings["exposure_ms"], actual_exposure))
    return actual_exposure, actual_gain


def acquire_pass(mic, positions, assignments, output, phase, repetition,
                 mode, brightfield=None, settle_seconds=0.5):
    is_fluorescence = mode.startswith("FLUO")
    # Close the fluorescence shutter before travelling or changing optical mode.
    if mic.isFluo():
        mic.setShutter(False)
    mic.setMode(mode)
    if is_fluorescence:
        mic.setShutter(False)
    folder = output / phase
    folder.mkdir(parents=True, exist_ok=True)
    for number, position in enumerate(positions, start=1):
        condition = assignments[number]
        settings = brightfield if brightfield is not None else condition
        mic.setPos(position)
        exposure, gain = apply_camera_settings(mic, settings)
        print("{} rep {} position {}/{} {}: {:.3f} ms, {:.2f} dB".format(
            phase, repetition, number, len(positions), condition["name"], exposure, gain), flush=True)
        time.sleep(settle_seconds)
        filename = folder / "rep{:04d}_pos{:03d}_{}_{}.tif".format(
            repetition, number, condition["name"], mode)
        try:
            mic.rec_image(str(filename))  # One image at the saved Z; no Z sweep.
        finally:
            # Also close after a camera/save error or Ctrl+C during acquisition.
            if is_fluorescence:
                mic.setShutter(False)


def run_protocol(mic, positions, assignments, output, repetitions, interval_seconds,
                 fluorescence_channel, brightfield_mode, brightfield, settle_seconds):
    try:
        acquire_pass(mic, positions, assignments, output, "brightfield_start", 0,
                     brightfield_mode, brightfield, settle_seconds)
        previous_start = None
        for repetition in range(1, repetitions + 1):
            if previous_start is not None:
                time.sleep(max(0.0, previous_start + interval_seconds - time.monotonic()))
            previous_start = time.monotonic()
            acquire_pass(mic, positions, assignments, output, "fluorescence", repetition,
                         fluorescence_channel, settle_seconds=settle_seconds)
        acquire_pass(mic, positions, assignments, output, "brightfield_end", 0,
                     brightfield_mode, brightfield, settle_seconds)
    finally:
        if mic.isFluo():
            mic.setShutter(False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Validate and preview without connecting to hardware")
    parser.add_argument("--positions", type=Path, default=POSITIONS_FILE)
    args = parser.parse_args()
    positions = load_positions(args.positions)
    assignments = condition_map(CONDITIONS, len(positions))
    for settings in CONDITIONS + [BRIGHTFIELD]:
        validate_settings(settings)
    if isinstance(FLUORESCENCE_REPETITIONS, bool) or not isinstance(FLUORESCENCE_REPETITIONS, int) or FLUORESCENCE_REPETITIONS < 1:
        raise ValueError("FLUORESCENCE_REPETITIONS must be a positive integer")
    if any(not math.isfinite(value) or value < 0 for value in (INTERVAL_SECONDS, SETTLE_SECONDS)):
        raise ValueError("Interval and settling times must be finite and non-negative")
    if FLUORESCENCE_CHANNEL not in ["FLUO{}".format(i) for i in range(1, 7)]:
        raise ValueError("Choose FLUO1 through FLUO6")
    if BRIGHTFIELD_MODE not in ("BF", "POL", "PH"):
        raise ValueError("Choose BF, POL, or PH for the brightfield pass")
    print("Order: brightfield at all positions -> {} fluorescence passes -> brightfield at all positions".format(FLUORESCENCE_REPETITIONS))
    for number in range(1, len(positions) + 1):
        group = assignments[number]
        print("Position {}: {} / {} / {} ms / {} dB".format(
            number, group["name"], FLUORESCENCE_CHANNEL, group["exposure_ms"], group["gain_db"]))
    if args.dry_run:
        print("Dry run complete; no microscope connection or images recorded.")
        return

    # Unique run folder prevents a later run from overwriting these images.
    output = OUTPUT_FOLDER / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(args.positions, output / "positions.txt")
    shutil.copy2(__file__, output / Path(__file__).name)
    manifest = dict(software_folder=str(SOFTWARE_FOLDER), positions_file=str(args.positions),
                    fluorescence_channel=FLUORESCENCE_CHANNEL, repetitions=FLUORESCENCE_REPETITIONS,
                    interval_seconds=INTERVAL_SECONDS, settle_seconds=SETTLE_SECONDS,
                    brightfield_mode=BRIGHTFIELD_MODE, brightfield=BRIGHTFIELD,
                    conditions=[dict(c, positions=list(c["positions"])) for c in CONDITIONS])
    (output / "protocol_settings.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    mic = load_microscope_class()()
    verify_camera_ranges(mic, CONDITIONS, BRIGHTFIELD)
    print("Recording to:", output, flush=True)
    run_protocol(mic, positions, assignments, output, FLUORESCENCE_REPETITIONS,
                 INTERVAL_SECONDS, FLUORESCENCE_CHANNEL, BRIGHTFIELD_MODE,
                 BRIGHTFIELD, SETTLE_SECONDS)
    print("Recording complete:", output, flush=True)


if __name__ == "__main__":
    main()
