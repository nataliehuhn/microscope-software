"""Characterize endpoint reproducibility of short pre-accelerated Z sweeps.

The study deliberately does not save the camera buffers.  It records only the
timestamp-derived frame positions and image summary statistics in a durable
manifest, and restores the exact starting microscope state after every trial.
"""

from __future__ import print_function

import argparse
import datetime
import json
import math
import traceback
from pathlib import Path

import numpy as np

from leica_microscope.microscope import Microscope


def json_value(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError("Cannot serialize {!r}".format(type(value)))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--distance-um", type=float, default=10.0)
    parser.add_argument("--requested-spacing-um", type=float, default=10.0)
    parser.add_argument("--frame-counts", default="2,3,4,5,6,7,8,10")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--camera-margin-frames", type=int, default=4)
    parser.add_argument("--label", default="study")
    return parser.parse_args()


def close_camera(mic):
    if mic is None or mic.cam is None:
        return
    camera = getattr(mic.cam, "camera", None)
    if camera is not None:
        if camera.IsGrabbing():
            camera.StopGrabbing()
        camera.Close()


def main():
    args = parse_args()
    frame_counts = [
        int(value.strip()) for value in args.frame_counts.split(",")
        if value.strip()
    ]
    if args.distance_um <= 0 or args.requested_spacing_um <= 0:
        raise ValueError("Distances and spacing must be positive")
    if args.repetitions < 1 or any(count < 2 for count in frame_counts):
        raise ValueError("Need at least one repetition and at least two frames")

    run_id = datetime.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S%z")
    run_dir = Path(__file__).resolve().parent / (
        "preaccelerated_reproducibility_{}_{}_{}".format(
            args.label, args.distance_um, run_id
        )
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = run_dir / "study_manifest.json"
    state = {
        "run_id": run_id,
        "run_directory": str(run_dir),
        "status": "initializing",
        "requested": vars(args),
        "frame_counts": frame_counts,
        "trials": [],
    }

    def save_manifest():
        state["updated_local"] = datetime.datetime.now().astimezone().isoformat()
        manifest_path.write_text(
            json.dumps(state, indent=2, sort_keys=True, default=json_value),
            encoding="utf-8",
        )

    save_manifest()
    mic = None
    start_pos = None
    start_speed = None
    active_error = None
    restoration_errors = []
    try:
        mic = Microscope()
        start_pos = mic.getPos()
        start_raw = mic.send_command_and_wait(
            ["72023", "73023", "71023"], [int, int, int]
        )
        start_speed = mic.getZSpeed()
        z_resolution = mic.getZResolution()
        # Stay at or just below the requested distance so an exact 10 um
        # request does not gain an unintended third endpoint-inclusive frame
        # from sub-step rounding.
        distance_steps = int(math.floor(args.distance_um / z_resolution))
        actual_distance_um = distance_steps * z_resolution
        z_range = mic.getZRange()
        max_model_acceleration = max(
            int(sample.get("acceleration_steps", 0))
            for sample in mic.preaccelerated_projection_model["samples"]
        )

        if np.any(mic.getMoving()):
            raise RuntimeError("The stage was moving at study preflight")
        if not (z_range[0] <= start_pos[2] + distance_steps <= z_range[1]):
            raise RuntimeError("Study endpoint is outside the reported Z range")

        state.update(
            {
                "status": "running",
                "start_position_processed_steps": start_pos,
                "start_position_raw_steps": start_raw,
                "start_z_speed": start_speed,
                "z_resolution_um_per_step": z_resolution,
                "distance_steps": distance_steps,
                "actual_distance_um": actual_distance_um,
                "z_range_steps": z_range,
                "camera": {
                    "backend": mic.config["camera"],
                    "fps": mic.cam.getFramerate(),
                    "exposure_ms": mic.cam.exposure(),
                    "width_px": mic.cam.getWidth(),
                    "height_px": mic.cam.getHeight(),
                },
                "model_path": str(mic.getPreacceleratedProjectionModelPath()),
                "model_created_local": mic.preaccelerated_projection_model.get(
                    "created_local"
                ),
                "model_max_acceleration_steps": max_model_acceleration,
            }
        )
        save_manifest()
        print("RUN_DIR={}".format(run_dir), flush=True)
        print(
            "START_POS={} DISTANCE_UM={:.4f} FPS={:.6f}".format(
                start_pos.tolist(), actual_distance_um, mic.cam.getFramerate()
            ),
            flush=True,
        )

        for minimum_frames in frame_counts:
            for repetition in range(1, args.repetitions + 1):
                before_pos = mic.getPos()
                before_speed = mic.getZSpeed()
                if not np.array_equal(before_pos, start_pos):
                    raise RuntimeError(
                        "Position was not restored before frame count {} repetition {}"
                        .format(minimum_frames, repetition)
                    )
                if before_speed != start_speed:
                    raise RuntimeError(
                        "Z speed was not restored before frame count {} repetition {}"
                        .format(minimum_frames, repetition)
                    )

                print(
                    "TRIAL minimum_frames={} repetition={}/{}".format(
                        minimum_frames, repetition, args.repetitions
                    ),
                    flush=True,
                )
                buffer, diagnostics = mic.recordPreacceleratedStackToBuffer(
                    int(start_pos[2]),
                    0,
                    distance_steps,
                    requested_spacing_um=args.requested_spacing_um,
                    minimum_frames=minimum_frames,
                    camera_margin_frames=args.camera_margin_frames,
                )
                after_pos = mic.getPos()
                after_speed = mic.getZSpeed()
                restored = bool(
                    np.array_equal(after_pos, start_pos)
                    and after_speed == start_speed
                    and not np.any(mic.getMoving())
                )
                trial = {
                    "minimum_frames": minimum_frames,
                    "repetition": repetition,
                    "diagnostics": diagnostics,
                    "image_min": int(np.min(buffer)),
                    "image_max": int(np.max(buffer)),
                    "image_mean": float(np.mean(buffer)),
                    "position_after_steps": after_pos,
                    "speed_after": after_speed,
                    "restored_exactly": restored,
                }
                state["trials"].append(trial)
                save_manifest()
                del buffer
                if not restored:
                    raise RuntimeError("Microscope state was not restored after trial")
                print(
                    "RESULT frames={} first={:+.3f}um last={:+.3f}um "
                    "coverage={:+.3f}um spacing={:.3f}+/-{:.3f}um".format(
                        diagnostics["frame_count"],
                        diagnostics["first_frame_error_um"],
                        diagnostics["last_frame_error_um"],
                        diagnostics["coverage_error_um"],
                        diagnostics["mean_frame_spacing_um"],
                        diagnostics["std_frame_spacing_um"],
                    ),
                    flush=True,
                )

        state["status"] = "recorded"
        save_manifest()
    except BaseException as error:
        active_error = error
        state["status"] = "failed"
        state["error"] = repr(error)
        state["traceback"] = traceback.format_exc()
        save_manifest()
        raise
    finally:
        if mic is not None and start_pos is not None:
            try:
                mic.setZSpeed(mic.getZSpeedMax())
                mic.setPos(start_pos)
                mic.setZSpeed(start_speed)
                final_pos = mic.getPos()
                final_speed = mic.getZSpeed()
                restored = bool(
                    np.array_equal(final_pos, start_pos)
                    and final_speed == start_speed
                    and not np.any(mic.getMoving())
                )
                state["final_position_processed_steps"] = final_pos
                state["final_z_speed"] = final_speed
                state["restored_exactly"] = restored
                if not restored:
                    restoration_errors.append("Final hardware state did not match")
            except BaseException as error:
                restoration_errors.append("State restore: {!r}".format(error))
        try:
            close_camera(mic)
        except BaseException as error:
            restoration_errors.append("Camera close: {!r}".format(error))
        state["restoration_errors"] = restoration_errors
        if active_error is None and not restoration_errors:
            state["status"] = "complete"
        elif restoration_errors:
            state["status"] = "restoration_failed"
        save_manifest()
        print(
            "RESTORED_EXACTLY={} FINAL_STATUS={}".format(
                state.get("restored_exactly"), state["status"]
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
