from __future__ import division, print_function
import os
import datetime
from pathlib import Path

from leica_microscope.includes.helper_functions import getConfig, modesToDictList, formatDict, print_with_border

config, timestamp = getConfig()

modes = modesToDictList(config.general.record_modes)

indent = 0
output_file = Path(config.files.target_folder) / (timestamp + "_record.py")
output_file.parent.mkdir(exist_ok=True)
# empty the target file
with output_file.open("w"):
    pass

def output(str):
    for line in str.strip().split("\n"):
        print("    "*indent + line.strip())
        with output_file.open("a") as fp:
            fp.write("    "*indent + line.strip()+"\n")

print_with_border("generate code")

output(f"""
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

if not (config.stack.slice_start == 0 and config.stack.slice_stop == 0) and config.stack.projection is True:
    output("")
    output("# calibrate the speed")
    output(f"mic.rec_calibrate_stack_speed(n_below={config.stack.slice_start}, n_above={config.stack.slice_stop}, slice_thickness_um={config.stack.slice_thickness})")

if config.grid.countx > 1 or config.grid.county > 1:
    output("")
    output(f"""
    # grid parameters
    overlap = {config.grid.overlap}
    startx, starty = {config.grid.startx}, {config.grid.starty}
    countx, county = {config.grid.countx}, {config.grid.county}
    dx = int(mic.cam.getWidth()*(1-overlap)*mic.cam.getPixelSize()/mic.getEffectiveMagnification()/mic.getXResolution())
    dy = int(mic.cam.getHeight()*(1-overlap)*mic.cam.getPixelSize()/mic.getEffectiveMagnification()/mic.getYResolution())
    """)

properties = {}

if config.repetition.repeat_positions_separately is True and config.files.positions_filename != None:
    output("")
    output("# iterate over positions")
    output(f"for pos_index, pos in enumerate(bar(positions, desc='position')):")
    indent += 1
    output("mic.setPos(pos)")
    properties["pos"] = "pos_index"

if config.repetition.repetition_count > 1:
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
    output("mic.setPos(pos)")
    properties["pos"] = "pos_index"

if len(modes) > 1:
    output("")
    output("# iterate over modes")
    output(f"for mode in bar(modes, desc='mode'):")
    indent += 1
    output("mic.setProperties(**mode)")
    properties["mode"] = "mode['mode']"

if config.grid.countx > 1 or config.grid.county > 1:
    output("")
    output("# start position for grid")
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
    output("mic.setPos(pos + np.array([grid_x*dx, grid_y*dy, 0]))")
    properties["x"] = "grid_x"
    properties["y"] = "grid_y"

if config.stack.slice_start == 0 and config.stack.slice_stop == 0:
    output("")
    if config.general.wait_before_image:
        output("# wait before image")
        output(f"time.sleep({config.general.wait_before_image})")
        output("")
    output("# record a single image")
    output(f"mic.rec_image(format_partial(filename, {formatDict(properties)}))")
elif config.stack.projection is True:
    output("")
    if config.general.wait_before_image:
        output("# wait before image")
        output(f"time.sleep({config.general.wait_before_image})")
        output("")
    output("# record a projection stack")
    output(f"mic.rec_projection(format_partial(filename, {formatDict(properties)}), n_below={config.stack.slice_start}, n_above={config.stack.slice_stop}, slice_thickness_um={config.stack.slice_thickness})")
else:
    output("")
    if config.general.wait_before_image:
        output("# wait before image")
        output(f"time.sleep({config.general.wait_before_image})")
        output("")
    output("# record a projection stack")
    output(f"mic.rec_stack(format_partial(filename, {formatDict(properties)}), n_below={config.stack.slice_start}, n_above={config.stack.slice_stop}, slice_thickness_um={config.stack.slice_thickness})")

# change to the target folder
os.chdir(output_file.parent)
# and execute the new script
start_time = datetime.datetime.now()
print_with_border("start measurement")
os.system("python " + output_file.name + " --timestamp=" + timestamp)
print_with_border("measurement finished")
print(f"duration {datetime.datetime.now()-start_time}")
