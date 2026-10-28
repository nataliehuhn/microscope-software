"""Characterize fast-projection calibration while reducing Z distance."""

from __future__ import print_function

import datetime
import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np

from leica_microscope.microscope import Microscope


SLICE_THICKNESS_UM = 10.0
INITIAL_DISTANCES_UM = [500, 250, 100, 50, 20, 10]
RUN_ID = datetime.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S%z")
RUN_DIR = Path(__file__).resolve().parent / ("projection_distance_sweep_" + RUN_ID)
MANIFEST = RUN_DIR / "sweep_manifest.json"


def json_value(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError("Cannot serialize {!r}".format(type(value)))


def save_manifest(state):
    state["updated_local"] = datetime.datetime.now().astimezone().isoformat()
    MANIFEST.write_text(
        json.dumps(state, indent=2, sort_keys=True, default=json_value),
        encoding="utf-8",
    )


def requested_distances_um():
    """Allow a targeted comma-separated sweep without changing this file."""
    prefix = "--distances-um="
    for argument in sys.argv[1:]:
        if argument.startswith(prefix):
            values = [
                float(value)
                for value in argument[len(prefix):].split(",")
                if value.strip()
            ]
            if not values:
                raise ValueError("--distances-um needs at least one distance")
            if any(value <= 0 or value % SLICE_THICKNESS_UM != 0 for value in values):
                raise ValueError(
                    "Every distance must be a positive multiple of {} um".format(
                        SLICE_THICKNESS_UM
                    )
                )
            return values
    return list(INITIAL_DISTANCES_UM)


def main():
    initial_distances_um = requested_distances_um()
    RUN_DIR.mkdir(parents=True, exist_ok=False)
    state = {
        "run_id": RUN_ID,
        "run_directory": str(RUN_DIR),
        "slice_thickness_um": SLICE_THICKNESS_UM,
        "initial_distances_um": initial_distances_um,
        "results": [],
        "status": "initializing",
    }
    save_manifest(state)

    mic = None
    start_pos = None
    start_speed = None
    active_result = None
    try:
        mic = Microscope()
        start_pos = mic.getPos()
        start_raw_pos = mic.send_command_and_wait(
            ["72023", "73023", "71023"], [int, int, int]
        )
        start_speed = mic.getZSpeed()
        max_speed = mic.getZSpeedMax()
        z_resolution = mic.getZResolution()
        slice_step = int(SLICE_THICKNESS_UM / z_resolution)
        z_range = mic.getZRange()
        if np.any(mic.getMoving()):
            raise RuntimeError("Stage is moving at sweep preflight")

        state.update(
            {
                "status": "running",
                "source_module": str(
                    Path(sys.modules["leica_microscope.microscope"].__file__).resolve()
                ),
                "start_position_processed_steps": start_pos,
                "start_position_raw_steps": start_raw_pos,
                "start_z_speed": start_speed,
                "z_max_speed": max_speed,
                "z_resolution_um_per_step": z_resolution,
                "slice_step_steps": slice_step,
                "actual_slice_step_um": slice_step * z_resolution,
                "z_range_steps": z_range,
                "camera": {
                    "backend": mic.config["camera"],
                    "exposure_ms": mic.cam.exposure(),
                    "framerate_fps": mic.cam.getFramerate(),
                    "width_px": mic.cam.getWidth(),
                    "height_px": mic.cam.getHeight(),
                    "dtype": mic.cam.getDtype().__name__,
                },
            }
        )
        save_manifest(state)
        print("RUN_DIR={}".format(RUN_DIR), flush=True)
        print("START_POS={}".format(start_pos.tolist()), flush=True)

        tested_slices = {}

        def run_distance(n_slices, phase):
            nonlocal active_result
            if n_slices in tested_slices:
                return tested_slices[n_slices]

            distance_um = n_slices * SLICE_THICKNESS_UM
            stop_offset = (n_slices + 2) * slice_step
            target_z = int(start_pos[2]) + stop_offset
            if not z_range[0] <= target_z <= z_range[1]:
                raise RuntimeError(
                    "{} um endpoint {} is outside Z range".format(
                        distance_um, target_z
                    )
                )

            active_result = {
                "phase": phase,
                "n_slices": n_slices,
                "requested_distance_um": distance_um,
                "commanded_travel_um_including_runout": stop_offset
                * z_resolution,
                "target_z_steps": target_z,
                "status": "calibrating",
            }
            state["results"].append(active_result)
            save_manifest(state)
            print(
                "\n=== {} um / {} frames ({}) ===".format(
                    distance_um, n_slices, phase
                ),
                flush=True,
            )

            calibration_start = time.time()
            calibration = mic.rec_calibrate_stack_speed(
                n_below=0,
                n_above=n_slices,
                slice_thickness_um=SLICE_THICKNESS_UM,
            )
            active_result["calibration_duration_s"] = (
                time.time() - calibration_start
            )
            active_result["calibration"] = calibration
            active_result["position_after_calibration_steps"] = mic.getPos()
            active_result["z_speed_after_calibration"] = mic.getZSpeed()

            if not np.array_equal(mic.getPos(), start_pos):
                raise RuntimeError("Calibration did not restore the starting position")
            if mic.getZSpeed() != start_speed:
                raise RuntimeError("Calibration did not restore the starting Z speed")

            if calibration["success"]:
                active_result["status"] = "recording"
                save_manifest(state)
                distance_dir = RUN_DIR / ("{:04d}um".format(int(distance_um)))
                distance_dir.mkdir(exist_ok=False)
                filename = distance_dir / (
                    "projection_{:04d}um_{}".format(int(distance_um), RUN_ID)
                    + "_{z}.tif"
                )
                recording_start = time.time()
                mic.rec_projection(
                    str(filename),
                    n_below=0,
                    n_above=n_slices,
                    slice_thickness_um=SLICE_THICKNESS_UM,
                )
                active_result["recording_duration_s"] = (
                    time.time() - recording_start
                )
                active_result["output_files"] = sorted(
                    str(path) for path in distance_dir.glob("*.tif")
                )
                active_result["status"] = "recorded"
            else:
                active_result["status"] = "skipped_unreachable"
                active_result["output_files"] = []

            # Restore and verify after every individual geometry rather than
            # relying only on the outer safety net.
            mic.setZSpeed(max_speed)
            mic.setPos(start_pos)
            mic.setZSpeed(start_speed)
            active_result["final_position_processed_steps"] = mic.getPos()
            active_result["final_z_speed"] = mic.getZSpeed()
            active_result["restored_exactly"] = bool(
                np.array_equal(mic.getPos(), start_pos)
                and mic.getZSpeed() == start_speed
                and not np.any(mic.getMoving())
            )
            if not active_result["restored_exactly"]:
                raise RuntimeError("Per-distance state restoration failed")

            tested_slices[n_slices] = active_result
            active_result = None
            save_manifest(state)
            return tested_slices[n_slices]

        for distance_um in initial_distances_um:
            run_distance(int(distance_um / SLICE_THICKNESS_UM), "initial")

        successful = sorted(
            n for n, result in tested_slices.items()
            if result["calibration"]["success"]
        )
        unreachable = sorted(
            n for n, result in tested_slices.items()
            if not result["calibration"]["success"]
        )
        if successful and unreachable:
            high_success = min(successful)
            lower_failures = [n for n in unreachable if n < high_success]
            if lower_failures:
                low_failure = max(lower_failures)
                while high_success - low_failure > 1:
                    midpoint = (low_failure + high_success) // 2
                    result = run_distance(midpoint, "boundary_search")
                    if result["calibration"]["success"]:
                        high_success = midpoint
                    else:
                        low_failure = midpoint
                state["boundary"] = {
                    "largest_unreachable_distance_um": low_failure
                    * SLICE_THICKNESS_UM,
                    "smallest_reachable_distance_um": high_success
                    * SLICE_THICKNESS_UM,
                }

        state["status"] = "complete"
        save_manifest(state)
    except BaseException as error:
        state["status"] = "failed"
        state["error"] = repr(error)
        state["traceback"] = traceback.format_exc()
        if active_result is not None:
            active_result["status"] = "failed"
            active_result["error"] = repr(error)
        save_manifest(state)
        raise
    finally:
        restoration_errors = []
        if mic is not None and start_pos is not None:
            for description, restore in (
                ("set maximum return speed", lambda: mic.setZSpeed(mic.getZSpeedMax())),
                ("restore XYZ", lambda: mic.setPos(start_pos)),
                ("restore original Z speed", lambda: mic.setZSpeed(start_speed)),
            ):
                try:
                    restore()
                except BaseException as error:
                    restoration_errors.append(
                        "{}: {!r}".format(description, error)
                    )
            try:
                final_pos = mic.getPos()
                final_speed = mic.getZSpeed()
                state["final_position_processed_steps"] = final_pos
                state["final_z_speed"] = final_speed
                state["restored_exactly"] = bool(
                    np.array_equal(final_pos, start_pos)
                    and final_speed == start_speed
                    and not np.any(mic.getMoving())
                )
            except BaseException as error:
                restoration_errors.append("verify restoration: {!r}".format(error))

        if mic is not None and mic.cam is not None:
            try:
                camera = getattr(mic.cam, "camera", None)
                if camera is not None:
                    if camera.IsGrabbing():
                        camera.StopGrabbing()
                    camera.Close()
            except BaseException as error:
                restoration_errors.append("close camera: {!r}".format(error))

        state["restoration_errors"] = restoration_errors
        if restoration_errors:
            state["status"] = "restoration_failed"
        save_manifest(state)
        print(
            "\nFINAL_STATUS={} RESTORED_EXACTLY={}".format(
                state["status"], state.get("restored_exactly", False)
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
