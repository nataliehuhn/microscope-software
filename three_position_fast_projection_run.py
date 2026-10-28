"""Live timing run: five fast cycles over three X positions on Mic2.

The current position is the last site. The two earlier sites are 3 and 6 mm
lower in X. This script uses only the isolated source tree and leaves the
original Leica installation untouched.
"""

import datetime
import json
import time
from pathlib import Path

import numpy as np

from leica_microscope.includes.helper_functions import format_partial
from leica_microscope.microscope import Microscope


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "test-run" / (
    "three_positions_fast_" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
)
REPETITIONS = 5
Z_START_UM = -300.0
Z_STOP_UM = 300.0
SCAN_TIME_S = 2.0
X_SPACING_UM = 3000.0


def main():
    process_started = time.perf_counter()
    mic = Microscope()
    origin = np.asarray(mic.getPos(), dtype=int)
    x_resolution = float(mic.getXResolution())
    z_resolution = float(mic.getZResolution())
    x_min, x_max = mic.getXRange()
    z_min, z_max = mic.getZRange()
    pitch = int(round(X_SPACING_UM / x_resolution))
    x_targets = [int(origin[0] - 2 * pitch),
                 int(origin[0] - pitch), int(origin[0])]
    if not all(x_min <= x <= x_max for x in x_targets):
        raise RuntimeError("A planned X position is outside the stage range")
    # The recorder computes its own velocity-dependent lead-in. This broad
    # 500-um guard is checked before any motion; the recorder checks exactly.
    z_guard_steps = int(round(500.0 / z_resolution))
    if not z_min <= origin[2] - z_guard_steps:
        raise RuntimeError("Insufficient lower Z clearance")
    if not origin[2] + z_guard_steps <= z_max:
        raise RuntimeError("Insufficient upper Z clearance")
    if mic.getMoving().any():
        raise RuntimeError("Stage is moving; refusing to start")

    OUTPUT.mkdir(parents=True, exist_ok=False)
    filename = mic.getDefaultFilename(OUTPUT)
    print("output", OUTPUT)
    print("origin XYZ steps", origin.tolist())
    print("X targets steps", x_targets)
    print("X spacing um", pitch * x_resolution)
    print("projection", Z_START_UM, Z_STOP_UM, SCAN_TIME_S)
    print("repetitions", REPETITIONS, "interval 0 s")

    manifest = {
        "origin_xyz_steps": origin.tolist(),
        "x_targets_steps": x_targets,
        "x_spacing_um": pitch * x_resolution,
        "z_resolution_um_per_step": z_resolution,
        "repetitions": REPETITIONS,
        "requested_offsets_um": [Z_START_UM, Z_STOP_UM],
        "requested_scan_time_s": SCAN_TIME_S,
        "passes": [],
    }
    measurement_started = time.perf_counter()
    manifest["startup_s"] = measurement_started - process_started
    problem = None
    try:
        with mic.timed_projection_session() as session:
            for rep in range(REPETITIONS):
                print("\ncycle", rep + 1, "/", REPETITIONS)
                for pos_index, target_x in enumerate(x_targets):
                    # Returning to the reference Z before lateral motion is
                    # deliberate; the Z return itself uses maximum Z speed.
                    session.finish_position()
                    move_started = time.perf_counter()
                    mic.setXPos(target_x)
                    actual_x = mic.getXPos()
                    move_finished = time.perf_counter()
                    if actual_x != target_x:
                        raise RuntimeError(
                            "X stage stopped at {}, expected {}".format(
                                actual_x, target_x
                            )
                        )
                    print("site", pos_index, "X move {:.3f}s".format(
                        move_finished - move_started), end=" ")
                    projection_started = time.perf_counter()
                    result = session.record(
                        format_partial(
                            filename, repetition=rep, pos=pos_index
                        ),
                        Z_START_UM, Z_STOP_UM, SCAN_TIME_S,
                    )
                    projection_finished = time.perf_counter()
                    manifest["passes"].append({
                        "repetition": rep,
                        "position_index": pos_index,
                        "x_target_steps": target_x,
                        "x_move_s": move_finished - move_started,
                        "projection_call_s": (
                            projection_finished - projection_started
                        ),
                        "elapsed_at_start_s": (
                            projection_started - measurement_started
                        ),
                        "actual_scan_time_s": result["actual_scan_time_s"],
                        "coverage_fraction": result["coverage_fraction"],
                        "selected_frame_count": result["selected_frame_count"],
                        "attempts": result["attempts"],
                        "phase_seconds": result.get("phase_seconds", {}),
                    })
        # The last scan was at the original X. The session restored its Z.
    except BaseException as exc:
        problem = repr(exc)
        raise
    finally:
        try:
            # On error, return to the original site only after restoring the
            # reference Z, so lateral motion never starts at a scan edge.
            if mic.getZPos() != int(origin[2]):
                previous_speed = mic.getZSpeed()
                try:
                    mic.setZSpeed(mic.getZSpeedMax())
                    mic.setZPos(int(origin[2]))
                finally:
                    mic.setZSpeed(previous_speed)
            if mic.getZPos() == int(origin[2]) and mic.getXPos() != int(origin[0]):
                mic.setXPos(int(origin[0]))
        finally:
            completed = time.perf_counter()
            manifest["measurement_s"] = completed - measurement_started
            manifest["total_with_initialization_s"] = completed - process_started
            manifest["error"] = problem
            try:
                manifest["final_xyz_steps"] = mic.getPos().tolist()
            except BaseException as exc:
                manifest["final_position_error"] = repr(exc)
            manifest["saved_bytes"] = mic.used_disk_space
            (OUTPUT / "timing_manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            print("\nmeasurement seconds", manifest["measurement_s"])
            print("total including initialization seconds",
                  manifest["total_with_initialization_s"])
            print("saved", mic.used_disk_space, "bytes")
            print("manifest", OUTPUT / "timing_manifest.json")


if __name__ == "__main__":
    main()
