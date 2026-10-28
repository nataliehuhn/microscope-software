"""Record one guarded pre-accelerated projection and restore hardware state."""

import argparse
import datetime
import json
import traceback
from pathlib import Path

import numpy as np
import tifffile

from leica_microscope.microscope import Microscope


def json_value(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError("Cannot serialize {!r}".format(type(value)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slice-count", type=int, default=100)
    parser.add_argument("--slice-thickness-um", type=float, default=10.0)
    parser.add_argument("--minimum-frames", type=int, default=None)
    parser.add_argument("--label", default="validation")
    args = parser.parse_args()
    if args.slice_count < 1 or args.slice_thickness_um <= 0:
        raise ValueError("Projection geometry must be positive")

    run_id = datetime.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S%z")
    run_dir = Path(__file__).resolve().parent / (
        "preaccelerated_projection_{}_{}".format(args.label, run_id)
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = run_dir / "run_manifest.json"
    state = {
        "run_id": run_id,
        "run_directory": str(run_dir),
        "status": "initializing",
        "requested": vars(args),
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
        slice_steps = int(args.slice_thickness_um / z_resolution)
        stop_z = int(start_pos[2]) + args.slice_count * slice_steps
        z_range = mic.getZRange()
        if np.any(mic.getMoving()):
            raise RuntimeError("Stage was moving at projection preflight")
        if not z_range[0] <= stop_z <= z_range[1]:
            raise RuntimeError("Projection endpoint is outside the Z range")

        state.update(
            {
                "status": "recording",
                "start_position_processed_steps": start_pos,
                "start_position_raw_steps": start_raw,
                "start_z_speed": start_speed,
                "z_resolution_um_per_step": z_resolution,
                "slice_steps": slice_steps,
                "actual_slice_thickness_um": slice_steps * z_resolution,
                "requested_stop_z_steps": stop_z,
                "model_path": str(mic.getPreacceleratedProjectionModelPath()),
                "model_created_local": mic.preaccelerated_projection_model.get(
                    "created_local"
                ),
                "camera": {
                    "backend": mic.config["camera"],
                    "fps": mic.cam.getFramerate(),
                    "exposure_ms": mic.cam.exposure(),
                    "width_px": mic.cam.getWidth(),
                    "height_px": mic.cam.getHeight(),
                },
            }
        )
        save_manifest()
        print("RUN_DIR={}".format(run_dir), flush=True)
        print(
            "START_POS={} STOP_Z={} SLICES={}".format(
                start_pos.tolist(), stop_z, args.slice_count
            ),
            flush=True,
        )

        filename = run_dir / ("projection_{}_{{z}}.tif".format(run_id))
        diagnostics = mic.rec_projection(
            str(filename),
            n_below=0,
            n_above=args.slice_count,
            slice_thickness_um=args.slice_thickness_um,
            minimum_frames=args.minimum_frames,
        )
        output_files = sorted(run_dir.glob("*.tif"))
        expected_outputs = 4
        if len(output_files) != expected_outputs:
            raise RuntimeError(
                "Expected {} TIFFs, found {}".format(
                    expected_outputs, len(output_files)
                )
            )
        validations = []
        for path in output_files:
            with tifffile.TiffFile(path) as image_file:
                array = image_file.asarray()
                description = image_file.pages[0].description or ""
            validations.append(
                {
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                    "shape": array.shape,
                    "dtype": str(array.dtype),
                    "minimum": int(np.min(array)),
                    "maximum": int(np.max(array)),
                    "contains_preaccelerated_metadata": (
                        "PreacceleratedProjection" in description
                    ),
                }
            )
        state["diagnostics"] = diagnostics
        state["output_files"] = validations
        state["position_after_recording_steps"] = mic.getPos()
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
        if mic is not None and mic.cam is not None:
            try:
                camera = getattr(mic.cam, "camera", None)
                if camera is not None:
                    if camera.IsGrabbing():
                        camera.StopGrabbing()
                    camera.Close()
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
