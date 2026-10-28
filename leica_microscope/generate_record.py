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

config, timestamp = getConfig()

modes = modesToDictList(config.general.record_modes)

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
from leica_microscope.includes.helper_functions import format_partial, bar
from leica_microscope.microscope import Microscope

# initialize the microscope connection
mic = Microscope()

# get the filename where to store the output
filename = mic.getDefaultFilename(r"{config.files.target_folder}")
""")

if config.files.positions_filename != None:
    output("")
    output("# load positions from a file")
    output(f"positions = mic.loadPositions(r'{config.files.positions_filename}')")

if len(modes) > 1:
    output("")
    output("# modes")
    output("modes = " + str(modes))
elif len(modes) == 1 and len(modes[0]) != 0:
    output("")
    output("# set the mode for recording")
    output(f"mic.setProperties({formatDict(modes[0], escape=True)})")

if config.general.wait_at_start > 0:
    output("")
    output("# wait before the measurement")
    output(f"print('Waiting before the measurement for {config.general.wait_at_start} minutes')")
    output(f"time.sleep({config.general.wait_at_start*60})")

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

# A batch may stay at a scan edge only when nothing else in the generated
# loops changes position or mode between repetitions.
optimized_series = (
    projection_mode == "optimized"
    and config.repetition.repetition_count > 1
    and config.files.positions_filename is None
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

if config.repetition.repeat_positions_separately is True and config.files.positions_filename != None:
    output("")
    output("# iterate over positions")
    output(f"for pos_index, pos in enumerate(bar(positions, desc='position')):")
    indent += 1
    if optimized_multisite:
        output("timed_series.finish_position()")
    output("mic.setPos(pos)")
    properties["pos"] = "pos_index"

if config.repetition.repetition_count > 1 and not optimized_series:
    output("")
    output("# iterate over repetitions")
    output(f"for rep in bar(range({config.repetition.repetition_count}), desc='repetition'):")
    indent += 1
    output(f"mic.waitSinceLast({config.repetition.repetition_time_delta})")
    properties["repetition"] = "rep"

if config.repetition.repeat_positions_separately is not True and config.files.positions_filename != None:
    output("")
    output("# iterate over positions")
    output(f"for pos_index, pos in enumerate(bar(positions, desc='position')):")
    indent += 1
    if optimized_multisite:
        output("timed_series.finish_position()")
    output("mic.setPos(pos)")
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
        output(
            f"mic.rec_timed_continuous_projection_series(filename, "
            f"z_start_um={z_start_um}, z_stop_um={z_stop_um}, "
            f"scan_time_s={scan_time_s}, "
            f"repetition_count={config.repetition.repetition_count}, "
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
