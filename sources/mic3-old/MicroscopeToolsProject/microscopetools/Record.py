# -*- coding: utf-8 -*-
from __future__ import division, print_function
import sys
import os
import time
import shutil
import numpy as np

start_total_time = time.time()
sys.path.append(os.path.dirname(__file__))
from microscopehandler.CameraClient import Camera
from microscopehandler.MicroscopeClient import microscope
from fast_autofocus import RecordZStack, RecordProj, RecordProjZStack
from HelperFunctions import format_partial, format_with_default, CheckPath, Config, getModes, print_with_border, print_revert, print_indented, set_format_zeros
import json
from datetime import datetime, timedelta

# Import default config
from Modes import Mode_Current, Mode_BF, Mode_POL, Mode_PH, Mode_Fluo1, Mode_Fluo2, Mode_Fluo3, Mode_Fluo4, Mode_Fluo5, Mode_Fluo6
#from Record_DefaultConfig import *


config_filename = os.path.expandvars(r"%APPDATA%\Microscope\Config.txt")

if len(sys.argv) >= 2:
    config_filename = sys.argv[1]
else:
    config_filename = r"C:\Users\Micro4\AppData\Roaming\Microscope\Config.txt"
print(config_filename)
# overwrite defaults with personal cfg if available
if os.path.exists(config_filename):
    config = Config(config_filename, os.path.join(os.path.dirname(__file__), "ConfigCreator", "Config_Default.txt"))
else:
    print("ERROR: no config file found.")
    sys.exit(-1)
    #execfile(config_filename)

# Check if path exists
target_folder = CheckPath(config.files.target_folder)

""" Connect to microscope """
print("\nConneting to microscope...")
mic = microscope()

# set Stage speeds
mic.setSpeedsToMax()

# get Resolution and image sizes
StepToMu = mic.getResolutionX()
StepToMuZ = mic.getResolutionZ()
magnification = mic.getEffectiveMagnification()

print("... connected")

""" Connect to camera """
print("\nConneting to camera server...")
mmc = Camera()
mmc.timeout_value = 60
mmc.saveStatus("Starting Measurement<br/><br/>", useBot=True)
#mmc.timeout_value = 30
sensor_size = mmc.getPixelSize()

imageSizeX = mmc.getImageWidth()
imageSizeY = mmc.getImageHeight()

was_running = mmc.isSequenceRunning()
"""
# set binning or roi
if config.general.roi:
    mmc.setBinning(1)
    roi = config.general.roi
    if isinstance(roi, int):
        crop = 1024 - roi
        print("Crop ", crop)
        mmc.setROI(0, crop / 2, 1344, 1024 - crop)
    else:
        if roi[0] == "[":
            roi = json.loads(roi)
        mmc.setROI(*roi)

if config.general.binning and config.general.binning != 1:
    mmc.setBinning(config.general.binning)
"""
print("... connected")

# define offset for grids
PixToMu = sensor_size/magnification
dx, dy = int(imageSizeX*(1-config.grid.overlap)*PixToMu/StepToMu), int(imageSizeY*(1-config.grid.overlap)*PixToMu/StepToMu)
dy = -dy

save_filename = r"{datetime}_{system}_rep{repetition}_pos{pos}_x{x}_y{y}_mode{mode}_z{z}.tif"
timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
save_filename = format_partial(save_filename, datetime=timestamp, system=mic.getMicroscopeName())
save_filename = os.path.join(target_folder, save_filename)

mmc.setBlockingProcess()

def TimeEstimation(add_count=0):
    #global index, total_count, start_time, start_index
    #time_estimate_per_positon = (time.time()-start_time)/(index-start_index)
    #time_estimate_total = time_estimate_per_positon*(total_count-index)
    #time_string = time.strftime("%H:%M:%S", time.gmtime(time_estimate_total))+" %3d" % ((time_estimate_total-int(time_estimate_total))*1000)
    #time_string_end = time.strftime("%a, %d %b %Y %H:%M:%S", time.gmtime(time.time()+time_estimate_total))
    #print("%d/%d" % (index, total_count), "Estimated Remaining Time", time_string)
    #mmc.saveStatus("Estimated Remaining Time "+time_string+"<br>\nEstimated Finish Time "+time_string_end)

    global total_image_count, recorded_images, start_record_time
    recorded_images += add_count
    time_estimate_per_position = (time.time() - start_record_time) / max(0.001, recorded_images)
    time_estimate_total = time_estimate_per_position * (total_image_count - recorded_images)
    time_duration = timedelta(seconds=int(time_estimate_total))
    time_end = (datetime.now()+time_duration).strftime("%a, %d %b %Y %H:%M:%S")
    percentage = int(recorded_images*20/total_image_count)
    print_revert("[%-20s] %d/%d" % ('='*percentage, recorded_images, total_image_count), "Estimated Remaining Time", time_duration)
    mmc.saveStatus("Estimated Remaining Time "+str(time_duration)+"<br>\nEstimated Finish Time "+str(time_end), percent="%d / %d" % (recorded_images, total_image_count))

def RecordStack(filename, execution_stack, indent=0):
    print("RecordStack")
    global recorded_images
    if config.general.wait_before_image:
        print_indented(indent, u"Sleeping "+str(config.general.wait_before_image)+" seconds before taking the image")
        time.sleep(config.general.wait_before_image)
    print_indented(indent, u"Recording stack %.2fum %d %d" % (config.stack.slice_thickness, config.stack.slice_start, config.stack.slice_stop))
    TimeEstimation()
    RecordZStack(mmc, mic, z=stack_position[2], slice_thickness=config.stack.slice_thickness, slice_start=config.stack.slice_start, slice_stop=config.stack.slice_stop, filename=filename, indent=indent+1, timeprint=TimeEstimation, continuous_sequence=config.general.continuous_sequence)
    TimeEstimation()

def RecordProjection(filename, execution_stack, indent=0):
    print("RecordProjection")
    global recorded_images
    if config.general.wait_before_image:
        print_indented(indent, u"Sleeping "+str(config.general.wait_before_image)+" seconds before taking the image")
        time.sleep(config.general.wait_before_image)
    TimeEstimation()
    RecordProj(mmc, mic, z=stack_position[2], slice_thickness=config.stack.slice_thickness, slice_start=config.stack.slice_start, slice_stop=config.stack.slice_stop, filename=filename, indent=indent, timeprint=TimeEstimation, continuous_sequence=config.general.continuous_sequence)
    #RecordProjZStack(mmc, mic, z=stack_position[2], slice_thickness=config.stack.slice_thickness, slice_start=config.stack.slice_start, slice_stop=config.stack.slice_stop, filename=filename, indent=indent, timeprint=TimeEstimation, continuous_sequence=config.general.continuous_sequence)
    TimeEstimation()

def RecordSingleImage(filename, execution_stack, indent=0):
    print("RecordSingleImage")
    global recorded_images
    mic.waitForMyCommands()
    if config.general.wait_before_image:
        print_indented(indent, u"Sleeping "+str(config.general.wait_before_image)+" seconds before taking the image")
        time.sleep(config.general.wait_before_image)
    if config.general.continuous_sequence:
        if not mmc.sequence_is_running:
            mmc.startContinuousSequenceAcquisition(1)
        # wait for one image
        mmc.clearImages()
        while mmc.getRemainingImageCount() == 0:
            time.sleep(0.01)
        # wait for a second image and discard the first image (the exposure could have started while the stage was still moving)
        mmc.clearImages()
        while mmc.getRemainingImageCount() == 0:
            time.sleep(0.1)
        # get this image
        img = mmc.getLastImage()
    else:
        mmc.snapImage()
        img = mmc.getImage()
    mmc.saveImage(format_with_default(filename, z=0), img, microscope=mic)
    print_indented(indent, "Image saved %s" % (format_with_default(filename, z=0)))
    TimeEstimation(1)

def RecordVideo(filename, execution_stack, indent=0):
    print("RecordVideo")
    global current_mode
    print("Use fast recording")
    mmc.startContinuousSequenceAcquisition(max(1, int(config.repetition.repetition_time_delta*1000.)))
    mmc.clearImages()
    last_time = time.time()
    start_time = time.time()
    for repetition in range(config.repetition.repetition_count):
        while not mmc.getRemainingImageCount() or time.time()-start_time < repetition*config.repetition.repetition_time_delta: pass
        img = mmc.getLastImage()
        print_indented(indent+1, "%d: %.2fs" % (repetition, time.time()-last_time))
        TimeEstimation(1)
        last_time = time.time()
        mmc.saveImage(format_with_default(filename, repetition=repetition), img, microscope=mic)
    mmc.stopSequenceAcquisition()

def Preparation(filename, execution_stack, indent=0):
    global current_mode
    current_mode.pre_measurement(mic, mmc)
    try:
        execution_stack[0](filename, execution_stack[1:], indent)
    except:
        # Emergency break: close shutter
        current_mode.post_measurement(mic, mmc)
        etype, evalue, etb = sys.exc_info()
        raise
    current_mode.post_measurement(mic, mmc)

def MoveToSinglePosition(filename, execution_stack, indent=0):
    global current_position, stack_position
    mic.setPos(current_position)
    stack_position = current_position[:]
    filename_xy = format_partial(filename, x=0, y=0)
    execution_stack[0](filename_xy, execution_stack[1:], indent)

def MoveToGrid(filename, execution_stack, indent=0):
    global current_position, stack_position
    global grid_y, grid_x
    pos = current_position+np.array([-dx+config.grid.startx*dx, -dy+config.grid.starty*dy, 0])
    mic.setPos(pos)
    # Iterate over y coordinates
    for grid_y in range(config.grid.starty, config.grid.starty+config.grid.county):
        mic.setYOffset(dy)
        # Iterate over x coordinates
        for grid_x in range(config.grid.startx, config.grid.startx+config.grid.countx):
            mic.setXOffset(dx)
            stack_position = pos + np.array([-dx+config.grid.startx*dx + dx*grid_x, -dy+config.grid.starty*dy + dy*grid_y, 0])
            if config.repetition.repetition_count > 1:
                print_indented(indent, "Repetition %d - Pos: %3d %3d" % (repetition, grid_x, grid_y))
            else:
                print_indented(indent, "Grid Pos: %3d %3d" % (grid_x, grid_y))
            TimeEstimation()
            filename_xy = format_partial(filename, x=grid_x, y=grid_y)
            execution_stack[0](filename_xy, execution_stack[1:], indent+1)
        # Move x back
        mic.setX(pos[0])
        mic.waitForMyCommands()

def IterateModes(filename, execution_stack, indent=0):
    global current_mode
    for mode in record_modes:
        current_mode = mode
        current_mode.set_mode(mic, mmc)
        filename_mode = format_partial(filename, mode=current_mode.name)
        print_indented(indent, "Mode %s" % (current_mode.name))
        TimeEstimation()
        execution_stack[0](filename_mode, execution_stack[1:], indent+1)

def IteratePositions(filename, execution_stack, indent=0):
    global current_position
    for pos_index, pos in enumerate(positions):
        print_indented(indent, "Position %d/%d" % (pos_index, len(positions)))
        current_position = pos
        filename_pos = format_partial(filename, pos=pos_index)
        execution_stack[0](filename_pos, execution_stack[1:], indent+1)

def IterateTimes(filename, execution_stack, indent=0):
    global repetition
    start_repetitions_time = time.time()
    for repetition in range(config.repetition.repetition_count):
        print_indented(indent, "Repetition %d/%d" % (repetition, config.repetition.repetition_count))
        TimeEstimation()
        filename_rep = format_partial(filename, repetition=repetition)
        # Should we launch a script before recording?
        if call_before_repetition != "":
            if os.system("python "+call_before_repetition): sys.exit(1)
        # Take a stack/grid at every position
        start_time = time.time()

        execution_stack[0](filename_rep, execution_stack[1:], indent+1)

        # Should we launch a script after recording?
        if call_after_repetition != "":
            if os.system("python "+call_after_repetition): sys.exit(1)
        # Should we launch a script between recording?
        if repetition != config.repetition.repetition_count-1 and call_between_repetition != "":
            if os.system("python "+call_between_repetition): sys.exit(1)
        # Should we wait until the next repetition?
        if repetition != config.repetition.repetition_count-1 and config.repetition.repetition_time_delta > 0:
            time_passsed = time.time()-start_repetitions_time
            start_time_next_repetition = (repetition+1)*config.repetition.repetition_time_delta
            if start_time_next_repetition - time_passsed > 0:
                print_indented(indent+1, "Waiting %d seconds" % (start_time_next_repetition - time_passsed))
                TimeEstimation()
                time.sleep(start_time_next_repetition - time_passsed)

call_before_repetition = config.calls.call_before_repetition
call_between_repetition = config.calls.call_between_repetition
call_after_repetition = config.calls.call_after_repetition
use_current_z = config.files.use_current_z

# Copy config to path
target_filename = None
if os.path.exists(config_filename):
    target_filename = os.path.join(target_folder, timestamp+"_"+os.path.split(config_filename)[1])
    try:
        shutil.copyfile(config_filename, target_filename)
    except shutil.Error:
        pass

# load positions or take current position
if config.files.positions_filename is not None:
    positions = np.loadtxt(config.files.positions_filename)
    if len(positions.shape) == 1:
        positions = np.array([positions])
    if use_current_z:
        current_z = mic.getZ()
        for pos in positions:
            pos[2] = current_z
    if positions.shape[0] == 1:
        current_position = positions[0]
        pos = current_position+np.array([-dx+config.grid.startx*dx, -dy+config.grid.starty*dy, 0])
        mic.setPos(pos)
        mic.waitTillEvent(moving=False)
        mic.setPos(current_position)
else:
    positions = np.array([mic.getPos()])
current_position = positions[0]
stack_position = current_position[:]

record_modes = []
for mode in getModes(config.general.record_modes):
    record_modes.append(eval(mode))

if len(record_modes) == 1:
    current_mode = record_modes[0]
    current_mode.set_mode(mic, mmc)

total_image_count = 1
recorded_images = 0
#abs(config.stack.slice_start-config.stack.slice_stop)*config.grid.countx*config.grid.county
execution_stack = []
if len(positions) == 1 and len(record_modes) == 1 and config.grid.countx == 1 and config.grid.county == 1 and config.stack.slice_start == config.stack.slice_stop:
    execution_stack = [RecordVideo]
    total_image_count = config.repetition.repetition_count
    save_filename = set_format_zeros(save_filename, "repetition", config.repetition.repetition_count)
else:
    ## repetitions and positions ##
    # repetitions (before positions)
    if config.repetition.repetition_count > 1 and config.repetition.repeat_positions_separately is False:
        execution_stack.append(IterateTimes)
        total_image_count *= config.repetition.repetition_count
        save_filename = set_format_zeros(save_filename, "repetition", config.repetition.repetition_count)
    # positions
    if len(positions) > 1:
        execution_stack.append(IteratePositions)
        total_image_count *= len(positions)
        save_filename = set_format_zeros(save_filename, "pos", len(positions))
    # repetitions (after positions)
    if config.repetition.repetition_count > 1 and config.repetition.repeat_positions_separately is True:
        execution_stack.append(IterateTimes)
        total_image_count *= config.repetition.repetition_count
        save_filename = set_format_zeros(save_filename, "repetition", config.repetition.repetition_count)

    ## modes and grid ##
    # record modes (before grid)
    if not config.grid.change_mode_single_image and len(record_modes) > 1 and record_modes[0] is not None:
        execution_stack.append(IterateModes)
        total_image_count *= len(record_modes)
    # grid
    if config.grid.countx > 1 or config.grid.county > 1:
        execution_stack.append(MoveToGrid)
        total_image_count *= config.grid.countx*config.grid.county
        save_filename = set_format_zeros(save_filename, "x", config.grid.countx)
        save_filename = set_format_zeros(save_filename, "y", config.grid.county)
    # single position
    elif len(positions) > 1:
        execution_stack.append(MoveToSinglePosition)
    # record modes (after grid)
    if config.grid.change_mode_single_image and len(record_modes) > 1 and record_modes[0] is not None:
        execution_stack.append(IterateModes)
        total_image_count *= len(record_modes)
        save_filename = set_format_zeros(save_filename, "pos", len(record_modes))

    ## images or stack ##
    # prepare
    execution_stack.append(Preparation)
    # single image
    if config.stack.slice_start == config.stack.slice_stop:
        #mmc.startContinuousSequenceAcquisition(1)
        mmc.stopSequenceAcquisition()
        execution_stack.append(RecordSingleImage)
    # projection
    elif config.stack.projection is True:
        execution_stack.append(RecordProjection)
    # stack
    else:
        execution_stack.append(RecordStack)
        total_image_count *= abs(config.stack.slice_start - config.stack.slice_stop) + 1
        save_filename = set_format_zeros(save_filename, "z",
                                         max(abs(config.stack.slice_start), abs(config.stack.slice_stop)))

if target_filename is not None:
    with open(target_filename, 'a') as fp:
        fp.write("[dynamic]\n")
        fp.write("filename = "+save_filename+"\n")
        fp.write("positions = " + str(positions.tolist()) + "\n")

index = 0
total_count = len(positions)*config.grid.countx*config.grid.county*config.repetition.repetition_count
start_position = mic.getPos()

print_with_border("Start Measurement")
mmc.saveStatus("Starting Measurement<br/><br/>", useBot=True)

start_record_time = time.time()
execution_stack[0](save_filename, execution_stack[1:])
    
print_with_border("Finished Measurement %.2fs" % (time.time()-start_total_time))
mmc.saveStatus("Finished Measurement %s<br/><br/>" % datetime.now().strftime("%a, %d %b %Y %H:%M:%S"), useBot=True)

if target_filename is not None:
    with open(target_filename, 'a') as fp:
        fp.write("finished = " + str(1) + "\n")

# reset stage and camera
mic.setPos(start_position)
mic.waitTillEvent(moving=False)
if was_running:
    mmc.startContinuousSequenceAcquisition(1)

mmc.setBlockingProcess(pid=0)
