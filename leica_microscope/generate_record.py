from __future__ import division, print_function
import os
import datetime
import math
import subprocess
import sys
from pathlib import Path

# Pin direct launches and generated experiments to this microscope checkout.
software_root = Path(__file__).resolve().parent.parent
if __package__ in (None, ""):
    sys.path.insert(0, str(software_root))

from leica_microscope.includes.helper_functions import getConfig, modesToDictList, formatDict
from leica_microscope.recording_sequence import SequenceSettings

config, timestamp = getConfig()

modes = modesToDictList(config.general.record_modes)
duration_hours = float(config.repetition.minimum_duration_hours) if config.has_option(
    "repetition", "minimum_duration_hours") else 0.0
if not math.isfinite(duration_hours) or duration_hours < 0:
    raise ValueError("Minimum recording duration must be finite and nonnegative")
duration_mode = duration_hours > 0
if duration_mode and (len(modes) != 1 or config.grid.countx != 1
                      or config.grid.county != 1):
    raise ValueError(
        "Duration recording needs one mode and a 1 x 1 grid; "
        "use one current or saved position"
    )
sequence_settings = SequenceSettings.from_config(config)
if (sequence_settings.position_order != "as_saved" or sequence_settings.settle_pattern
        ) and config.files.positions_filename is None:
    raise ValueError("Choose a positions file to use a position sequence or settling pattern")
if duration_mode and sequence_settings.cycle_count != 1:
    raise ValueError("Duration recording needs exactly one full cycle")

if config.has_option("stack", "projection_mode"):
    projection_mode = config.stack.projection_mode
    if projection_mode in ("timed", "legacy"):
        projection_mode = {"timed": "optimized", "legacy": "default"}[projection_mode]
        if config.has_option("stack", "projection") and not config.stack.projection:
            projection_mode = "off"
else:
    projection_mode = (
        "default" if config.has_option("stack", "projection")
        and config.stack.projection else "off"
    )
if projection_mode not in ("off", "default", "optimized"):
    raise ValueError("Unknown projection mode: {!r}".format(projection_mode))

indent = 0
output_file = Path(config.files.target_folder).resolve() / (timestamp + "_record.py")
output_file.parent.mkdir(parents=True, exist_ok=True)
# empty the target file
with output_file.open("w"):
    pass

def output(str):
    for line in str.strip().split("\n"):
        print("    "*indent + line.strip())
        with output_file.open("a") as fp:
            fp.write("    "*indent + line.strip()+"\n")

print("=== generate code ===")

output(f"""
import sys
sys.path.insert(0, {str(software_root)!r})
import numpy as np
import time
from pathlib import Path
from leica_microscope.includes.helper_functions import format_partial, bar
from leica_microscope.microscope import Microscope
from leica_microscope.recording_sequence import SequenceSettings, load_sequence_positions, position_indices, write_sequence_manifest, recording_cycles, cycle_output_folder, wait_for_position_repeat
sequence_settings = {sequence_settings!r}
""")

if config.files.positions_filename != None:
    output("")
    output("# load positions from a file")
    output(f"positions = load_sequence_positions({str(config.files.positions_filename)!r})")
    if duration_mode:
        output('if len(positions) != 1: raise ValueError("Duration recording needs exactly one saved position")')
    output("visit_order = position_indices(len(positions), sequence_settings.position_order, sequence_settings.positions_per_condition)")
    output(f"write_sequence_manifest({str(output_file.with_name(timestamp + '_position_sequence.json'))!r}, positions, sequence_settings)")

output("# initialize only after the position file and sequence have been validated")
output("mic = Microscope()")
if config.general.wait_at_start > 0:
    output(f"time.sleep({config.general.wait_at_start * 60})")
if duration_mode and config.files.positions_filename is not None:
    output("mic.setPos(positions[0])")

if sequence_settings.cycle_count > 1:
    if config.files.positions_filename is None:
        output("cycle_origin = mic.getPos()")
    output("for cycle in recording_cycles(sequence_settings.cycle_count, sequence_settings.cycle_interval_hours):")
    indent += 1
    if config.files.positions_filename is None:
        output("mic.setPos(cycle_origin)")
    output(f"cycle_folder = cycle_output_folder({str(output_file.parent / (timestamp + '_cycles'))!r}, cycle, sequence_settings.cycle_interval_hours)")
    output("filename = mic.getDefaultFilename(str(cycle_folder))")
    output("mic.iteration_time = None")
else:
    output(f"filename = mic.getDefaultFilename({str(output_file.parent)!r})")

if len(modes) > 1:
    output("")
    output("# modes")
    output("modes = " + str(modes))
elif len(modes) == 1 and len(modes[0]) != 0:
    output("")
    output("# set the mode for recording")
    output(f"mic.setProperties({formatDict(modes[0], escape=True)})")

if config.grid.countx > 1 or config.grid.county > 1:
    output("")
    output(f"""
    # grid parameters
    overlap = {config.grid.overlap}
    startx, starty = {config.grid.startx}, {config.grid.starty}
    countx, county = {config.grid.countx}, {config.grid.county}
    dx = int(mic.cam.getWidth()*(1-overlap)*mic.cam.getPixelSize()/mic.getEffectiveMagnification()/mic.getXResolution())
    dy = -int(mic.cam.getHeight()*(1-overlap)*mic.cam.getPixelSize()/mic.getEffectiveMagnification()/mic.getYResolution())
    """)

properties = {}
if duration_mode and config.files.positions_filename is not None:
    properties["pos"] = "0"

def output_position_move():
    output("pos = positions[pos_index]")
    if optimized_multisite:
        output("timed_series.finish_position()")
    output("mic.setPos(pos)")
    if sequence_settings.settle_pattern:
        output("time.sleep(sequence_settings.settle_pattern[visit_index % len(sequence_settings.settle_pattern)])")

# A batch may stay at a scan edge only when nothing else in the generated
# loops changes position or mode between repetitions.
optimized_series = (
    projection_mode == "optimized"
    and (config.repetition.repetition_count > 1 or duration_mode)
    and (config.files.positions_filename is None or duration_mode)
    and config.grid.countx == 1 and config.grid.county == 1
    and len(modes) == 1
)
optimized_multisite = (
    projection_mode == "optimized"
    and not optimized_series
    and (config.repetition.repetition_count > 1 or len(modes) > 1)
)
if optimized_multisite:
    output("")
    output("# keep adjacent optimized passes at their scan edge")
    output("with mic.timed_projection_session() as timed_series:")
    indent += 1

if (not duration_mode and config.repetition.repeat_positions_separately is True
        and config.files.positions_filename != None):
    output("")
    output("# iterate over positions")
    output("for visit_index, pos_index in enumerate(bar(visit_order, desc='position')):")
    indent += 1
    output_position_move()
    output("last_repeat_start = None")
    properties["pos"] = "pos_index"

if (config.repetition.repetition_count > 1 or duration_mode) and not optimized_series:
    output("")
    output("# iterate over repetitions")
    if duration_mode:
        output("from leica_microscope.recording_schedule import duration_repetitions")
        output("for rep in duration_repetitions(mic.waitSinceLast, "
               f"{duration_hours * 3600!r}, "
               f"{float(config.repetition.repetition_time_delta)!r}):")
    else:
        output(f"for rep in bar(range({config.repetition.repetition_count}), desc='repetition'):")
    indent += 1
    if not duration_mode:
        if config.repetition.repeat_positions_separately is True and config.files.positions_filename is not None:
            output(f"last_repeat_start = wait_for_position_repeat(last_repeat_start, {config.repetition.repetition_time_delta})")
        else:
            output(f"mic.waitSinceLast({config.repetition.repetition_time_delta})")
    properties["repetition"] = "rep"

if (not duration_mode and config.repetition.repeat_positions_separately is not True
        and config.files.positions_filename != None):
    output("")
    output("# iterate over positions")
    output("for visit_index, pos_index in enumerate(bar(visit_order, desc='position')):")
    indent += 1
    output_position_move()
    properties["pos"] = "pos_index"

if len(modes) > 1:
    output("")
    output("# iterate over modes")
    output(f"for mode in bar(modes, desc='mode'):")
    indent += 1
    output("mic.setProperties(**mode)")
    if optimized_multisite:
        output("timed_series.invalidate_preflight()")
    properties["mode"] = "mode['mode']"

if config.grid.countx > 1 or config.grid.county > 1:
    output("")
    output("# start position for grid")
    if optimized_multisite:
        output("timed_series.finish_position()")
    output("pos = mic.getPos()")
    output("mic.setPos(pos + np.array([-dx+startx*dx, -dy+starty*dy, 0]))")
    output("")
    output("# iterate over y coordinates of grid")
    output(f"for grid_y in bar(range(starty, starty+county), desc='grid y'):")
    indent += 1
    output("")
    output("# iterate over x coordinates of grid")
    output(f"for grid_x in bar(range(startx, startx+countx), desc='grid x'):")
    indent += 1
    if optimized_multisite:
        output("timed_series.finish_position()")
    output("mic.setPos(pos + np.array([grid_x*dx, grid_y*dy, 0]))")
    properties["x"] = "grid_x"
    properties["y"] = "grid_y"

output("")
if config.general.wait_before_image and not optimized_series:
    output("# wait before image")
    output(f"time.sleep({config.general.wait_before_image})")
    output("")

if projection_mode == "optimized":
    z_start_um = float(config.stack.projection_start_um)
    z_stop_um = float(config.stack.projection_stop_um)
    scan_time_s = float(config.stack.projection_time_s)
    if not all(math.isfinite(value) for value in (
            z_start_um, z_stop_um, scan_time_s)):
        raise ValueError("Optimized projection settings must be finite")
    if z_start_um == z_stop_um:
        raise ValueError("Optimized projection needs nonzero Z distance")
    if scan_time_s < 0.25:
        raise ValueError("Optimized projection time must be at least 0.25 s")
    if optimized_series:
        output("# alternate timed passes without returning to center between repetitions")
        duration_argument = (
            f"duration_s={duration_hours * 3600!r}, " if duration_mode else ""
        )
        count_argument = "None" if duration_mode else str(config.repetition.repetition_count)
        output(
            f"mic.rec_timed_continuous_projection_series(filename, "
            f"z_start_um={z_start_um}, z_stop_um={z_stop_um}, "
            f"scan_time_s={scan_time_s}, "
            f"repetition_count={count_argument}, {duration_argument}"
            f"repetition_time_delta={config.repetition.repetition_time_delta}, "
            f"wait_before_image_s={config.general.wait_before_image})"
        )
    elif optimized_multisite:
        output("# record an alternating optimized projection")
        output(
            f"timed_series.record(format_partial(filename, {formatDict(properties)}), "
            f"z_start_um={z_start_um}, z_stop_um={z_stop_um}, "
            f"scan_time_s={scan_time_s})"
        )
    else:
        output("# record a verified continuous projection using the raw TIFF format")
        output(
            f"mic.rec_timed_continuous_projection(format_partial(filename, {formatDict(properties)}), "
            f"z_start_um={z_start_um}, z_stop_um={z_stop_um}, "
            f"scan_time_s={scan_time_s})"
        )
elif projection_mode == "default":
    if config.stack.slice_start == config.stack.slice_stop:
        raise ValueError("Default projection needs nonzero Z distance")
    output("# record the existing slice-width projection")
    output(f"mic.rec_projection(format_partial(filename, {formatDict(properties)}), n_below={config.stack.slice_start}, n_above={config.stack.slice_stop}, slice_thickness_um={config.stack.slice_thickness})")
elif config.stack.slice_start == 0 and config.stack.slice_stop == 0:
    output("# record a single image")
    output(f"mic.rec_image(format_partial(filename, {formatDict(properties)}))")
else:
    output("# record an ordinary Z-stack")
    output(f"mic.rec_stack(format_partial(filename, {formatDict(properties)}), n_below={config.stack.slice_start}, n_above={config.stack.slice_stop}, slice_thickness_um={config.stack.slice_thickness})")

# and execute the new script
start_time = datetime.datetime.now()
print("=== start measurement ===")
subprocess.run(
    [sys.executable, str(output_file), "--timestamp=" + timestamp],
    cwd=str(output_file.parent), check=True,
)
print("=== measurement finished ===")
print(f"duration {datetime.datetime.now()-start_time}")
