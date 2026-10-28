"""Record the INT 4 / AP 7 timed continuous projection series.

Run from this copied repository with its local package on PYTHONPATH.  The
normal recording GUI is not modified and does not call this experiment.
"""

import datetime
import json
import traceback
from pathlib import Path

import numpy as np
import tifffile

from leica_microscope.microscope import Microscope


DURATIONS_S = (1, 2, 4, 8, 16)
OUTPUT = Path(__file__).resolve().parent / "INT_4_AP_7"


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def main():
    run_id = datetime.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S%z")
    output_min = OUTPUT / "min_projections"
    output_max = OUTPUT / "max_projections"
    output_min.mkdir(parents=True, exist_ok=True)
    output_max.mkdir(parents=True, exist_ok=True)
    manifest_path = OUTPUT / "run_{}.json".format(run_id)
    record = {
        "run_id": run_id,
        "status": "initializing",
        "requested": {
            "center_relative_z_um": [-100, 100],
            "durations_s": list(DURATIONS_S),
            "transmitted_light_intensity": 4,
            "transmitted_light_aperture": 7,
        },
        "scans": [],
    }
    save_json(manifest_path, record)
    mic = None
    original = None
    try:
        mic = Microscope()
        if mic.send_command_and_wait("70028", int) != mic.MODE_TL_BF:
            raise RuntimeError("Expected transmitted-light brightfield mode")
        if np.any(mic.getMoving()):
            raise RuntimeError("The microscope stage is moving")
        original = {
            "position_steps": mic.getPos().tolist(),
            "z_speed": mic.getZSpeed(),
            "exposure_ms": mic.cam.exposure(),
            "lamp_intensity": mic.getLampIntensity(),
            "aperture": mic.send_command_and_wait("84023", int),
            "shutter": mic.send_command_and_wait("77033", [int, int])[-1],
            "mode": mic.send_command_and_wait("70028", int),
            "z_resolution_um_per_step": mic.getZResolution(),
        }
        record["original_hardware"] = original
        save_json(manifest_path, record)
        print("START_POSITION_STEPS={}".format(original["position_steps"]), flush=True)

        mic.setLampIntensity(4)
        mic.setApertureTL(7)
        mic.setShutter(True)
        # The acquisition method will choose this near-continuous exposure too.
        max_fps = mic.cam.getMaximumFramerateAtShortExposure()
        mic.cam.setExposure(1000.0 / max_fps - 0.26)
        image = mic.cam.getImage()
        preflight = {
            "mean": float(image.mean()),
            "p99": float(np.quantile(image, 0.99)),
            "maximum": int(image.max()),
            "exposure_ms": float(mic.cam.exposure()),
            "fps": float(mic.cam.getFramerate()),
            "intensity": mic.getLampIntensity(),
            "aperture": mic.send_command_and_wait("84023", int),
            "shutter": mic.send_command_and_wait("77033", [int, int])[-1],
        }
        record["preflight"] = preflight
        save_json(manifest_path, record)
        print("PREFLIGHT={}".format(preflight), flush=True)
        if preflight["intensity"] != 4 or preflight["aperture"] != 7:
            raise RuntimeError("INT 4 / AP 7 settings were not applied")
        if preflight["mean"] < 1 or preflight["p99"] < 5:
            raise RuntimeError(
                "Camera image is nearly black at INT 4 / AP 7; "
                "check illumination and optical path before recording"
            )

        record["status"] = "recording"
        save_json(manifest_path, record)
        for duration in DURATIONS_S:
            name = "{}_{}s.tif".format(run_id, duration)
            min_path = output_min / ("min_" + name)
            max_path = output_max / ("max_" + name)
            if min_path.exists() or max_path.exists():
                raise FileExistsError("Projection file already exists for {}s".format(duration))
            if mic.getZPos() != original["position_steps"][2]:
                raise RuntimeError("Stage did not return to the starting Z")
            minimum, maximum, diagnostics = mic.recordTimedContinuousProjection(
                -100, 100, duration
            )
            if diagnostics["coverage_fraction"] < 0.98:
                raise RuntimeError(
                    "Only {:.1%} Z coverage for {}s".format(
                        diagnostics["coverage_fraction"], duration
                    )
                )
            metadata = {
                "ProjectionMethod": "timed_continuous",
                "RequestedScanTimeSeconds": duration,
                "ActualScanTimeSeconds": diagnostics["actual_scan_time_s"],
                "RequestedStartOffsetMicrometers": -100,
                "RequestedStopOffsetMicrometers": 100,
                "ExposureCoverageFraction": diagnostics["coverage_fraction"],
            }
            mic.saveImage(str(min_path), minimum, dict(metadata, Projection="min"))
            mic.saveImage(str(max_path), maximum, dict(metadata, Projection="max"))
            for path in (min_path, max_path):
                with tifffile.TiffFile(path) as saved:
                    if saved.asarray().shape != minimum.shape:
                        raise RuntimeError("Saved projection has an unexpected shape")
            record["scans"].append({
                "duration_s": duration,
                "min_file": str(min_path),
                "max_file": str(max_path),
                "min_image_mean": float(minimum.mean()),
                "max_image_mean": float(maximum.mean()),
                "max_image_p99": float(np.quantile(maximum, 0.99)),
                "diagnostics": diagnostics,
            })
            save_json(manifest_path, record)
            print(
                "RECORDED {}s: actual {:.3f}s, {} frames, {:.3%} coverage, "
                "max gap {:.3f} um".format(
                    duration, diagnostics["actual_scan_time_s"],
                    diagnostics["selected_frame_count"],
                    diagnostics["coverage_fraction"],
                    diagnostics["maximum_unexposed_gap_um"],
                ), flush=True,
            )
        record["status"] = "complete"
    except BaseException as error:
        record["status"] = "failed"
        record["error"] = repr(error)
        record["traceback"] = traceback.format_exc()
        raise
    finally:
        if mic is not None and original is not None:
            restore_errors = []
            for name, operation in (
                    ("position", lambda: mic.setZPos(original["position_steps"][2])),
                    ("z_speed", lambda: mic.setZSpeed(original["z_speed"])),
                    ("exposure", lambda: mic.cam.setExposure(original["exposure_ms"])),
                    ("intensity", lambda: mic.setLampIntensity(original["lamp_intensity"])),
                    ("aperture", lambda: mic.setApertureTL(original["aperture"])),
                    ("shutter", lambda: mic.setShutter(original["shutter"])),
            ):
                try:
                    operation()
                except BaseException as error:
                    restore_errors.append("{}: {!r}".format(name, error))
            record["restored_hardware"] = {
                "position_steps": mic.getPos().tolist(),
                "z_speed": mic.getZSpeed(),
                "exposure_ms": mic.cam.exposure(),
                "lamp_intensity": mic.getLampIntensity(),
                "aperture": mic.send_command_and_wait("84023", int),
                "shutter": mic.send_command_and_wait("77033", [int, int])[-1],
                "restore_errors": restore_errors,
            }
            mic.cam.camera.Close()
        save_json(manifest_path, record)
        print("MANIFEST={}".format(manifest_path), flush=True)


if __name__ == "__main__":
    main()
