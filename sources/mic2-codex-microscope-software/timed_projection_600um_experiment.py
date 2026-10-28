"""Record a validated ±300 µm timed series; save only contrast TIFFs.

Raw min/max arrays stay in memory until all five durations have passed timing
and coverage checks. No unenhanced projection image is written to disk.
"""

import datetime
import json
import traceback
from pathlib import Path

import numpy as np
import tifffile

from leica_microscope.microscope import Microscope


DURATIONS_S = (1, 2, 4, 8, 16)
TIMING_TOLERANCE_FRACTION = 0.03
MAX_ATTEMPTS_PER_DURATION = 3
LOW_QUANTILE = 0.001
HIGH_QUANTILE = 0.9999
OUTPUT_PARENT = Path(__file__).resolve().parent / "INT_4_AP_7"


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def quantile_from_histogram(histogram, quantile):
    total = int(histogram.sum())
    return int(np.searchsorted(np.cumsum(histogram), quantile * total))


def main():
    run_id = datetime.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S%z")
    output = OUTPUT_PARENT / ("600um_" + run_id)
    output.mkdir(parents=True, exist_ok=False)
    manifest_path = output / "run_manifest.json"
    manifest = {
        "run_id": run_id,
        "status": "initializing",
        "requested": {
            "z_offsets_um": [-300, 300],
            "scan_times_s": list(DURATIONS_S),
            "intensity": 4,
            "aperture": 7,
            "timing_tolerance_fraction": TIMING_TOLERANCE_FRACTION,
        },
        "attempts": [],
        "outputs": [],
    }
    write_json(manifest_path, manifest)
    mic = None
    original = None
    accepted = []
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
            "intensity": mic.getLampIntensity(),
            "aperture": mic.send_command_and_wait("84023", int),
            "shutter": mic.send_command_and_wait("77033", [int, int])[-1],
            "z_resolution_um_per_step": mic.getZResolution(),
        }
        manifest["original_hardware"] = original
        write_json(manifest_path, manifest)
        print("START_POSITION_STEPS={}".format(original["position_steps"]), flush=True)

        mic.setLampIntensity(4)
        mic.setApertureTL(7)
        mic.setShutter(True)
        max_fps = mic.cam.getMaximumFramerateAtShortExposure()
        mic.cam.setExposure(1000.0 / max_fps - 0.26)
        preflight_image = mic.cam.getImage()
        preflight = {
            "mean": float(preflight_image.mean()),
            "p99": float(np.quantile(preflight_image, 0.99)),
            "max": int(preflight_image.max()),
            "exposure_ms": mic.cam.exposure(),
            "fps": mic.cam.getFramerate(),
            "intensity": mic.getLampIntensity(),
            "aperture": mic.send_command_and_wait("84023", int),
            "shutter": mic.send_command_and_wait("77033", [int, int])[-1],
        }
        manifest["preflight"] = preflight
        write_json(manifest_path, manifest)
        print("PREFLIGHT={}".format(preflight), flush=True)
        if preflight["intensity"] != 4 or preflight["aperture"] != 7:
            raise RuntimeError("INT 4 / AP 7 settings were not applied")
        if preflight["mean"] < 1 or preflight["p99"] < 5:
            raise RuntimeError("Camera image is too dark to record")

        manifest["status"] = "acquiring"
        write_json(manifest_path, manifest)
        for duration in DURATIONS_S:
            speed_override = None
            for attempt_number in range(1, MAX_ATTEMPTS_PER_DURATION + 1):
                if mic.getZPos() != original["position_steps"][2]:
                    raise RuntimeError("Stage did not return to starting Z")
                minimum, maximum, diagnostics = mic.recordTimedContinuousProjection(
                    -300, 300, duration, speed_override=speed_override
                )
                actual = diagnostics["actual_scan_time_s"]
                relative_error = (actual - duration) / duration
                valid_timing = abs(relative_error) <= TIMING_TOLERANCE_FRACTION
                valid_coverage = diagnostics["coverage_fraction"] >= 0.98
                attempt = {
                    "requested_duration_s": duration,
                    "attempt_number": attempt_number,
                    "actual_duration_s": actual,
                    "relative_timing_error": relative_error,
                    "valid_timing": valid_timing,
                    "valid_coverage": valid_coverage,
                    "diagnostics": diagnostics,
                }
                manifest["attempts"].append(attempt)
                write_json(manifest_path, manifest)
                print(
                    "ATTEMPT {}s #{}: actual {:.3f}s ({:+.2%}), {} frames, "
                    "{:.3%} coverage".format(
                        duration, attempt_number, actual, relative_error,
                        diagnostics["selected_frame_count"],
                        diagnostics["coverage_fraction"],
                    ), flush=True,
                )
                if valid_timing and valid_coverage:
                    metadata = mic.getMetadata().copy()
                    metadata.update(mic.cam.getMetadata())
                    accepted.append((duration, minimum, maximum, diagnostics, metadata))
                    break
                if attempt_number == MAX_ATTEMPTS_PER_DURATION:
                    raise RuntimeError(
                        "{}s scan did not meet timing/coverage limits after {} attempts"
                        .format(duration, MAX_ATTEMPTS_PER_DURATION)
                    )
                if not valid_coverage:
                    # Dropped or mistimed frames are not repaired by a speed
                    # adjustment, but one repeated acquisition may recover.
                    speed_override = diagnostics["selected_speed"]
                else:
                    speed_override = int(round(
                        diagnostics["selected_speed"] * actual / duration
                    ))
                    speed_override = max(
                        mic.getZSpeedMin(),
                        min(mic.getZSpeedMax(), speed_override),
                    )
        manifest["status"] = "acquired_validated"
    except BaseException as error:
        manifest["status"] = "failed"
        manifest["error"] = repr(error)
        manifest["traceback"] = traceback.format_exc()
        raise
    finally:
        if mic is not None and original is not None:
            restore_errors = []
            for name, operation in (
                    ("z_position", lambda: mic.setZPos(original["position_steps"][2])),
                    ("z_speed", lambda: mic.setZSpeed(original["z_speed"])),
                    ("exposure", lambda: mic.cam.setExposure(original["exposure_ms"])),
                    ("intensity", lambda: mic.setLampIntensity(original["intensity"])),
                    ("aperture", lambda: mic.setApertureTL(original["aperture"])),
                    ("shutter", lambda: mic.setShutter(original["shutter"])),
            ):
                try:
                    operation()
                except BaseException as error:
                    restore_errors.append("{}: {!r}".format(name, error))
            try:
                manifest["restored_hardware"] = {
                    "position_steps": mic.getPos().tolist(),
                    "z_speed": mic.getZSpeed(),
                    "exposure_ms": mic.cam.exposure(),
                    "intensity": mic.getLampIntensity(),
                    "aperture": mic.send_command_and_wait("84023", int),
                    "shutter": mic.send_command_and_wait("77033", [int, int])[-1],
                    "restore_errors": restore_errors,
                }
            finally:
                mic.cam.camera.Close()
        write_json(manifest_path, manifest)
        print("MANIFEST={}".format(manifest_path), flush=True)

    if manifest["status"] != "acquired_validated":
        raise RuntimeError("Validated acquisitions are not available")
    if manifest["restored_hardware"]["restore_errors"]:
        raise RuntimeError("Hardware restoration reported an error")

    # Determine one reproducible display transform for all 10 projections.
    histogram = np.zeros(256, dtype=np.int64)
    for _, minimum, maximum, _, _ in accepted:
        histogram += np.bincount(minimum.ravel(), minlength=256)
        histogram += np.bincount(maximum.ravel(), minlength=256)
    low = quantile_from_histogram(histogram, LOW_QUANTILE)
    high = quantile_from_histogram(histogram, HIGH_QUANTILE)
    if high <= low:
        raise RuntimeError("Projection intensities have no usable contrast range")
    values = np.arange(256, dtype=np.float64)
    lookup = np.clip(
        np.rint((values - low) * 255.0 / (high - low)), 0, 255
    ).astype(np.uint8)
    manifest["contrast"] = {
        "method": "shared_linear_percentile_window",
        "input_low": low,
        "input_high": high,
        "output_low": 0,
        "output_high": 255,
        "low_quantile": LOW_QUANTILE,
        "high_quantile": HIGH_QUANTILE,
        "below_window_pixel_count": int(histogram[:low].sum()),
        "above_window_pixel_count": int(histogram[high + 1:].sum()),
        "note": "Enhanced projections are display-only, not quantitative raw intensities.",
    }
    (output / "min_projections").mkdir()
    (output / "max_projections").mkdir()
    for duration, minimum, maximum, diagnostics, metadata in accepted:
        for kind, image in (("min", minimum), ("max", maximum)):
            enhanced = lookup[image]
            destination = output / (kind + "_projections") / (
                "{}_600um_{}s_contrast.tif".format(kind, duration)
            )
            enhanced_metadata = dict(metadata)
            enhanced_metadata.update({
                "Projection": kind,
                "ProjectionMethod": "timed_continuous",
                "RequestedStartOffsetMicrometers": -300,
                "RequestedStopOffsetMicrometers": 300,
                "RequestedScanTimeSeconds": duration,
                "ActualScanTimeSeconds": diagnostics["actual_scan_time_s"],
                "ExposureCoverageFraction": diagnostics["coverage_fraction"],
                "DisplayContrastMethod": "shared_linear_percentile_window",
                "DisplayContrastInputLow": low,
                "DisplayContrastInputHigh": high,
                "DisplayContrastOutputLow": 0,
                "DisplayContrastOutputHigh": 255,
                "DisplayOnlyNoRawProjectionSaved": True,
            })
            tifffile.imwrite(
                destination, enhanced, photometric="minisblack",
                metadata=enhanced_metadata,
            )
            with tifffile.TiffFile(destination) as saved:
                verified = saved.asarray()
                verified_metadata = json.loads(saved.pages[0].description)
            if not np.array_equal(verified, enhanced):
                raise RuntimeError("Saved projection failed pixel verification")
            if verified_metadata["DisplayContrastInputLow"] != low:
                raise RuntimeError("Saved contrast metadata did not verify")
            manifest["outputs"].append({
                "requested_duration_s": duration,
                "projection": kind,
                "path": str(destination),
                "shape": list(enhanced.shape),
                "pixel_range": [int(enhanced.min()), int(enhanced.max())],
            })
            write_json(manifest_path, manifest)
            print("SAVED={}".format(destination), flush=True)
    manifest["status"] = "complete"
    write_json(manifest_path, manifest)
    print("CONTRAST_WINDOW={}..{}".format(low, high), flush=True)
    print("COMPLETE={}".format(output), flush=True)


if __name__ == "__main__":
    main()
