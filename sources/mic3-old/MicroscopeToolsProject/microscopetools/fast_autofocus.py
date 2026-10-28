from __future__ import division, print_function
from scipy.ndimage.filters import sobel
import numpy as np
import time
import matplotlib.pyplot as plt
from HelperFunctions import format_with_default, print_indented


def RecordZStack(mmc, mic, z=None, slice_thickness=10, slice_start=-10, slice_stop=10, filename="Stacks%d.tif", indent=0, timeprint=None, continuous_sequence=False):
    global images, z_positions, StepToMu, sharp
    SingleImages = not continuous_sequence
    StepToMu = mic.getResolutionZ()

    if slice_start > slice_stop:
        slice_start, slice_stop = (slice_stop, slice_start)

    slice_thickness /= StepToMu
    slice_thickness = int(slice_thickness)

    z_positions = np.arange(slice_start, slice_stop + 2) * slice_thickness

    if z is None:
        z = mic.getZ()
    mic.setZ(z + z_positions[0])

    if not SingleImages:
        mmc.startContinuousSequenceAcquisition(1)
    else:
        mmc.stopSequenceAcquisition()

    mic.waitForMyCommands()

    # if the sequence is running all the time, we have to discard the first image
    if continuous_sequence:
        # wait for one image
        mmc.clearImages()
        while mmc.getRemainingImageCount() == 0:
            time.sleep(0.01)
        mmc.clearImages()

    mmc.clearImages()
    last_image = len(z_positions[1:])-1
    for index, z_offset in enumerate(z_positions[1:]):
        t = time.time()
        if SingleImages:
            mmc.snapImage()
            if index != last_image:
                mic.setZ(z + z_offset)
            img = mmc.getImage()
            mmc.saveImage(format_with_default(filename, z=index), img, microscope=mic)
            if index != last_image:
                mic.waitForMyCommands()
        else:
            while not mmc.getRemainingImageCount():
                pass
            img = mmc.getLastImage()
            cmd = mic.setZ(z + z_offset)
            mmc.saveImage(format_with_default(filename, z=index), img, microscope=mic)
            if index != last_image:
                mic.waitForCommand(cmd)
            mmc.clearImages()
        print_indented(indent, "Z Slice: %d/%d (%.2fs)       " % (index, slice_stop - slice_start, time.time() - t))
        if timeprint: timeprint(1)
    mic.setZ(z)
    mic.waitForMyCommands()



def RecordProjZStack(mmc, mic, z=None, slice_thickness=10, slice_start=-10, slice_stop=10, filename="Stacks%d.tif", indent=0, timeprint=None, continuous_sequence=False):
    global images, z_positions, StepToMu, sharp
    SingleImages = not continuous_sequence
    StepToMu = mic.getResolutionZ()

    if slice_start > slice_stop:
        slice_start, slice_stop = (slice_stop, slice_start)

    slice_thickness /= StepToMu
    slice_thickness = int(slice_thickness)

    z_positions = np.arange(slice_start, slice_stop + 2) * slice_thickness

    if z is None:
        z = mic.getZ()
    mic.setZ(z + z_positions[0])

    if not SingleImages:
        mmc.startContinuousSequenceAcquisition(1)
    else:
        mmc.stopSequenceAcquisition()

    mic.waitForMyCommands()

    # if the sequence is running all the time, we have to discard the first image
    if continuous_sequence:
        # wait for one image
        mmc.clearImages()
        while mmc.getRemainingImageCount() == 0:
            time.sleep(0.01)
        mmc.clearImages()

    # initialize the images for the projection
    h, w = 1024, 1344
    min_proj = np.zeros((h, w), dtype=np.uint16) + 4095
    max_proj = np.zeros((h, w), dtype=np.uint16)
    min_indices = np.zeros((h, w), dtype=np.uint16)
    max_indices = np.zeros((h, w), dtype=np.uint16)

    mmc.clearImages()
    last_image = len(z_positions[1:])-1

    for shot_idx, z_offset in enumerate(z_positions[1:]):
        t = time.time()
        if SingleImages:
            mmc.snapImage()
            if shot_idx != last_image:
                mic.setZ(z + z_offset)
            shot = mmc.getImage()
            #mmc.saveImage(format_with_default(filename, z=index), img, microscope=mic)
            if shot_idx != last_image:
                mic.waitForMyCommands()
        else:
            while not mmc.getRemainingImageCount():
                pass
            shot = mmc.getLastImage()
            cmd = mic.setZ(z + z_offset)
            #mmc.saveImage(format_with_default(filename, z=index), img, microscope=mic)
            if shot_idx != last_image:
                mic.waitForCommand(cmd)
            mmc.clearImages()

        # create minimum projection
        # try:
        mask = shot < min_proj
        min_proj[mask] = shot[mask]
        min_indices[mask] = shot_idx
        # except:
        #   pass

        # create maximum projection
        # try:
        mask = shot > max_proj
        max_proj[mask] = shot[mask]
        max_indices[mask] = shot_idx
        # except:
        #    pass

        shot_idx += 1

        print_indented(indent, "Z Slice: %d/%d (%.2fs)       " % (shot_idx, slice_stop - slice_start, time.time() - t))
        if timeprint: timeprint(1)

    # save minimum projection
    mmc.saveImage(format_with_default(filename, z='MinProj'), min_proj, microscope=mic)
    mmc.saveImage(format_with_default(filename, z='MaxProj'), max_proj, microscope=mic)
    mmc.saveImage(format_with_default(filename, z='MinIndices{}'.format(shot_idx)), min_indices, microscope=mic)
    mmc.saveImage(format_with_default(filename, z='MaxIndices{}'.format(shot_idx)), max_indices, microscope=mic)

    mic.setZ(z)
    mic.waitForMyCommands()


calibrated_proj_speed = None


def RecordProj(mmc, mic, z=None, slice_thickness=10, slice_start=-10, slice_stop=10, filename="proj.tif", indent=0, timeprint=None, continuous_sequence=False):
    global calibrated_proj_speed

    # get resolution
    StepToMu = mic.getResolutionZ()

    # ensure that stack is always recorded from bottom to top
    if slice_start > slice_stop:
        slice_start, slice_stop = (slice_stop, slice_start)

    # convert thickness to steps
    slice_thickness /= StepToMu
    slice_thickness = int(slice_thickness)

    # convert start/end to steps
    z_start = slice_start * slice_thickness
    z_stop = (slice_stop + 2) * slice_thickness
    n_slices = np.abs(slice_stop - slice_start)
    print("slices", slice_start, slice_stop, n_slices)

    # get position and move to start
    if z is None:
        z = mic.getZ()
    mic.setZ(z + z_start)

    # start recording
    if not mmc.sequence_is_running:
        mmc.startContinuousSequenceAcquisition(1)
        mmc.clearImages()

    # if the sequence is running all the time, we have to discard the first image
    if continuous_sequence:
        # wait for one image
        mmc.clearImages()
        while mmc.getRemainingImageCount() == 0:
            time.sleep(0.01)
        mmc.clearImages()

    # Calculate the approximate speed to get the desired number of images using the current framerate
    if calibrated_proj_speed is None:
        t = time.time()
        # print status
        print_indented(indent, "Started calibration of z-speed for projection...")
        if timeprint: timeprint()

        mic.setZSpeed(88200, wait=True)
        current_z_speed = mic.getZSpeed()
        print("current_z_speed", current_z_speed)

        # wait some seconds and get average fps
        time.sleep(4.5)  # to have accurate FPS
        fps = 0
        for i in range(5):
            fps += mmc.memmap.fps
            time.sleep(0.1)
        fps /= 5.

        mic.setZ(z + z_start, wait=True)
        t = time.time()
        cmd = mic.setZ(z + z_stop)
        while not mic.isCommandFinished(cmd):
            pass
        duration_drive = time.time()-t
        duration_take_images = n_slices / fps
        print("n_slices", n_slices)
        print("duration_drive", duration_drive)
        print("duration_take_images", duration_take_images)

        calibrated_proj_speed = int(duration_drive / duration_take_images * current_z_speed)
        print("calibrated_proj_speed", calibrated_proj_speed)


        # set speed according to stack size and fps
        #distance = np.abs(z_start - z_stop) / StepToMu
        #duration = n_slices / fps
        #calibrated_proj_speed = current_z_speed * distance/duration#mic.getSpeedForDistance(np.abs(z_start - z_stop) / StepToMu, n_slices / fps)
        print_indented(indent, "Calibrated z-Speed for Projection: %.6f * (max speed)." % (calibrated_proj_speed / 8820000))
        if timeprint: timeprint()

    # a while True loop to be able to retry the stack if an error occurs
    while True:

        # initialize arrays
        #h, w = 2192, 2752
        h, w = 1024, 1344
        min_proj = np.zeros((h, w), dtype=np.uint16) + 4095
        max_proj = np.zeros((h, w), dtype=np.uint16)
        min_indices = np.zeros((h, w), dtype=np.uint16)
        max_indices = np.zeros((h, w), dtype=np.uint16)

        # move to the start position and set the speed
        try:
            mic.setZSpeed(8820000)
            mic.setZ(z + z_start)
            cmd = mic.setZSpeed(calibrated_proj_speed)
        except mic.MicroscopeError:
            continue
        # wait for the commands to finish
        while not mic.isCommandFinished(cmd):
            pass
        if cmd.error != 0:
            continue
        # start the z movement
        cmd = mic.setZ(z + z_stop)
        shot_idx = 0
        t_start = time.time()
        # wait for command to start
        while not mic.isCommandStarted(cmd):
            pass
        mmc.clearImages()
        # record while the stage is moving
        while not mic.isCommandFinished(cmd):
            while not mmc.getRemainingImageCount():
                pass
            shot = mmc.popNextImage()

            # create minimum projection
            #try:
            mask = shot < min_proj
            min_proj[mask] = shot[mask]
            min_indices[mask] = shot_idx
            #except:
            #   pass

            # create maximum projection
            #try:
            mask = shot > max_proj
            max_proj[mask] = shot[mask]
            max_indices[mask] = shot_idx
            #except:
            #    pass

            shot_idx += 1
        if cmd.error == 0:
            break
        print("An error occurred, retrying stack")

    # save minimum projection
    mmc.saveImage(format_with_default(filename, z='MinProj'), min_proj, microscope=mic)
    mmc.saveImage(format_with_default(filename, z='MaxProj'), max_proj, microscope=mic)
    mmc.saveImage(format_with_default(filename, z='MinIndices{}'.format(shot_idx)), min_indices, microscope=mic)
    mmc.saveImage(format_with_default(filename, z='MaxIndices{}'.format(shot_idx)), max_indices, microscope=mic)

    # print status
    msg = "Projection: %d slices (estimated %d). Duration: %.2fs" % (shot_idx, n_slices, time.time() - t_start)
    print_indented(indent, msg)
    if timeprint: timeprint(1)

    # reset speed and position
    mic.setZSpeed(8820000)
    mic.setZ(z)


def GetZDrift(mmc, slice_thickness=10, slice_count=21, StartSequence=1, viewer=None):
    global images, sobel, z_positions, StepToMu, sharp
    mic = mmc
    StepToMu = mic.getResolutionZ()
    if StepToMu < 0.0001:
        StepToMu = 0.0038
    slice_thickness = int(slice_thickness // StepToMu)
    halft_slice_count = slice_count // 2

    z = mic.getZ()
    mic.setZOffset(-halft_slice_count * slice_thickness)

    was_running = mmc.isSequenceRunning()
    if was_running:
        mmc.stopSequenceAcquisition()
    old_roi = mmc.getROI()
    mmc.clearROI()
    h = mmc.getImageHeight()
    w = mmc.getImageWidth()
    mmc.setROI(w // 4, h // 4, w // 2, h // 2)
    mmc.startContinuousSequenceAcquisition(1)

    images = np.zeros([slice_count, mmc.getImageHeight(), mmc.getImageWidth()], dtype=np.uint16)
    z_positions = np.arange(-halft_slice_count, halft_slice_count + 1) * slice_thickness
    sharp = np.zeros(slice_count)

    mmc.clearImages()
    for index, z_offset in enumerate(z_positions):
        while not mmc.getRemainingImageCount():
            pass
        images[index, :, :] = mmc.getLastImage()
        zoffset = mic.setZOffset(slice_thickness, nowait=1)

        im = images[index]
        im = im / max([np.amax(im), 0.01])  # don't divide by zero
        sobelX = sobel(im / np.amax(im), 0) / 2
        sobelY = sobel(im / np.amax(im), 1) / 2
        sobelAll = np.sqrt(sobelX ** 2 + sobelY ** 2)
        sharp[index] = np.std(sobelAll)

        mic.wait_till_answer(zoffset)
        mmc.clearImages()

    mmc.stopSequenceAcquisition()
    mmc.setROI(*old_roi)
    if was_running:
        mmc.startContinuousSequenceAcquisition(1)

    index = np.argmax(sharp)
    # plt.plot(z_positions*StepToMu, sharp)

    if index == 0 or index == len(sharp) - 1:
        print("ERROR too much out of focus")
        delta_z = 0
    else:
        corrected_index = sum(sharp[index - 1:index + 2] * np.array([-1, 0, 1])) / np.sum(
            sharp[index - 1:index + 2]) + index
        delta_z = (corrected_index - halft_slice_count) * slice_thickness
    print("Autofocus", delta_z * StepToMu)
    mic.setZ(z + delta_z)
    return delta_z
