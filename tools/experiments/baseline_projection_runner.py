"""Run one baseline fast projection while restoring the microscope state.

This wrapper deliberately calls the copied code's existing calibration and
projection methods without changing their behavior. It adds preflight range
checks, a durable run manifest, and best-effort state restoration.
"""

from __future__ import print_function

import datetime
import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np

from leica_microscope.microscope import Microscope


SLICE_START = 0
SLICE_STOP = 100
SLICE_THICKNESS_UM = 10.0
RUN_ID = datetime.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S%z")
RUN_DIR = Path(__file__).resolve().parent / ("baseline_projection_" + RUN_ID)
MANIFEST = RUN_DIR / "run_manifest.json"


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


def main():
    RUN_DIR.mkdir(parents=True, exist_ok=False)
    state = {
        "run_id": RUN_ID,
        "run_directory": str(RUN_DIR),
        "requested": {
            "direction": "upward according to existing positive n_above semantics",
            "slice_start": SLICE_START,
            "slice_stop": SLICE_STOP,
            "slice_thickness_um": SLICE_THICKNESS_UM,
        },
        "status": "initializing",
    }
    save_manifest(state)

    mic = None
    start_pos = None
    start_z_speed = None
    restored = False
    error = None

    try:
        mic = Microscope()
        start_pos = mic.getPos()
        start_pos_raw = mic.send_command_and_wait(
            ["72023", "73023", "71023"], [int, int, int]
        )
        start_z_speed = mic.getZSpeed()
        z_range = mic.getZRange()
        z_resolution = mic.getZResolution()
        slice_step = int(SLICE_THICKNESS_UM / z_resolution)
        z_start_offset = SLICE_START * slice_step
        z_stop_offset = (SLICE_STOP + 2) * slice_step
        target_z = int(start_pos[2]) + z_stop_offset
        n_slices = abs(SLICE_STOP - SLICE_START)

        if np.any(mic.getMoving()):
            raise RuntimeError("The stage was moving at the recording preflight")
        if not (z_range[0] <= int(start_pos[2]) + z_start_offset <= z_range[1]):
            raise RuntimeError("Projection start is outside the reported Z range")
        if not (z_range[0] <= target_z <= z_range[1]):
            raise RuntimeError("Projection endpoint is outside the reported Z range")
        if n_slices <= 0:
            raise RuntimeError("Projection requires at least one frame")

        camera = {
            "backend": mic.config["camera"],
            "exposure_ms": mic.cam.exposure(),
            "framerate_fps": mic.cam.getFramerate(),
            "width_px": mic.cam.getWidth(),
            "height_px": mic.cam.getHeight(),
            "dtype": mic.cam.getDtype().__name__,
        }
        state.update(
            {
                "status": "preflight_complete",
                "source_module": str(
                    Path(sys.modules["leica_microscope.microscope"].__file__).resolve()
                ),
                "start_position_processed_steps": start_pos,
                "start_position_raw_steps": start_pos_raw,
                "start_z_speed": start_z_speed,
                "z_range_steps": z_range,
                "z_resolution_um_per_step": z_resolution,
                "slice_step_steps": slice_step,
                "actual_slice_step_um": slice_step * z_resolution,
                "n_frames": n_slices,
                "commanded_start_z_steps": int(start_pos[2]) + z_start_offset,
                "commanded_stop_z_steps": target_z,
                "commanded_travel_um_including_runout": z_stop_offset
                * z_resolution,
                "camera": camera,
            }
        )
        save_manifest(state)
        print("RUN_DIR={}".format(RUN_DIR), flush=True)
        print(
            "START_POS={} TARGET_Z={} FRAMES={} CAMERA_FPS={}".format(
                start_pos.tolist(), target_z, n_slices, camera["framerate_fps"]
            ),
            flush=True,
        )

        state["status"] = "calibrating"
        state["calibration_started_local"] = (
            datetime.datetime.now().astimezone().isoformat()
        )
        save_manifest(state)
        calibration_start = time.time()
        calibration = mic.rec_calibrate_stack_speed(
            n_below=SLICE_START,
            n_above=SLICE_STOP,
            slice_thickness_um=SLICE_THICKNESS_UM,
        )
        state["calibration_duration_s"] = time.time() - calibration_start
        state["calibrated_z_speed"] = mic.calibrated_proj_speed
        state["calibration"] = calibration
        state["position_after_calibration_steps"] = mic.getPos()
        state["status"] = "recording"
        save_manifest(state)

        filename = RUN_DIR / ("baseline_projection_" + RUN_ID + "_{z}.tif")
        recording_start = time.time()
        mic.rec_projection(
            str(filename),
            n_below=SLICE_START,
            n_above=SLICE_STOP,
            slice_thickness_um=SLICE_THICKNESS_UM,
        )
        state["recording_duration_s"] = time.time() - recording_start
        state["position_after_recording_steps"] = mic.getPos()
        state["output_files"] = sorted(str(path) for path in RUN_DIR.glob("*.tif"))
        state["status"] = "recorded"
        save_manifest(state)
    except BaseException as exc:
        error = exc
        state["status"] = "failed"
        state["error"] = repr(exc)
        state["traceback"] = traceback.format_exc()
        save_manifest(state)
        raise
    finally:
        restoration_errors = []
        if mic is not None and start_pos is not None:
            try:
                if start_z_speed is not None:
                    mic.setZSpeed(start_z_speed)
                mic.setPos(start_pos)
                final_pos = mic.getPos()
                final_speed = mic.getZSpeed()
                restored = bool(
                    np.array_equal(final_pos, start_pos)
                    and final_speed == start_z_speed
                    and not np.any(mic.getMoving())
                )
                state["final_position_processed_steps"] = final_pos
                state["final_z_speed"] = final_speed
                state["restored_exactly"] = restored
                if not restored:
                    restoration_errors.append(
                        "Final position/speed did not exactly match the starting state"
                    )
            except BaseException as exc:
                restoration_errors.append(repr(exc))

        if mic is not None and mic.cam is not None:
            try:
                camera = getattr(mic.cam, "camera", None)
                if camera is not None:
                    if camera.IsGrabbing():
                        camera.StopGrabbing()
                    camera.Close()
            except BaseException as exc:
                restoration_errors.append("Camera close: {!r}".format(exc))

        state["restoration_errors"] = restoration_errors
        if error is None and restored and not restoration_errors:
            state["status"] = "complete"
        elif restoration_errors:
            state["status"] = "restoration_failed"
        save_manifest(state)
        print(
            "RESTORED_EXACTLY={} FINAL_STATUS={}".format(
                restored, state["status"]
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
