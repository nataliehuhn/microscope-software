from __future__ import print_function, division
import sys
import numpy as np
import matplotlib.pyplot as plt
import clickpoints
import os
from scipy.interpolate import interp1d
from scipy import signal
import scipy.integrate as inte
import scipy.optimize as opt
import pyperclip
import glob
from datetime import datetime
import natsort
import numpy as np
from scipy.signal import argrelextrema
from scipy.signal import savgol_filter as sf

# define tracking parameter
import cv2

lk_params = dict(winSize=(64, 64), maxLevel=5, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03))


# get meta data of images
def get_meta(file):
    import tifffile
    import json
    from distutils.version import LooseVersion

    if LooseVersion(tifffile.__version__) > LooseVersion("0.13"):
        with tifffile.TiffFile(file) as tif:
            metadata = tif.shaped_metadata
            try:
                t = tif.shaped_metadata[0]["Time"]
            except KeyError:
                return None
            try:
                return datetime.strptime(t, '%Y%m%d-%H%M%S')
            except ValueError:
                try:
                    return datetime.strptime(t, '%Y%m%d-%H%M%S-%f')
                except ValueError:
                    return None
    else:
        try:
            with tifffile.TiffFile(file) as tif:
                try:
                    tif.shaped_metadata[0]
                except AttributeError:
                    try:
                        metadata = tif[0].image_description
                    except (TypeError, AttributeError):
                        return None
                try:
                    t = json.loads(metadata.decode('utf-8'))["Time"]
                except (AttributeError, ValueError, KeyError):
                    return None
                try:
                    return datetime.strptime(t, '%Y%m%d-%H%M%S')
                except ValueError:
                    try:
                        return datetime.strptime(t, '%Y%m%d-%H%M%S-%f')
                    except ValueError:
                        return None
        except ValueError:  # invalid tiff file
            return None


class Addon(clickpoints.Addon):
    def __init__(self, *args, **kwargs):
        clickpoints.Addon.__init__(self, *args, **kwargs)

        # find a track type
        for type in self.db.getMarkerTypes():
            if type.mode == self.db.TYPE_Track:
                break
        else:
            # if no track type is found, create one
            self.db.setMarkerType("track", "#FFFF00", self.db.TYPE_Track)
            self.cp.reloadTypes()

        plt.figure(0)
        plt.clf()
        plt.figure(1)
        plt.clf()

    def run(self, start_frame=0, do_tracking=True):

        if do_tracking:
            self.doTracking()

        tracks, diff_seconds = self.getTracks()

        count = 0
        plt.figure(0)

        # go through all tracks and do the evaluation
        for track in tracks:
            points = track.points
            if count == 0:
                count = 1
                points0 = points
                continue
            # calculate distances
            distancesP = abs(points[:, 0] - points0[:, 0])

            # get absolute times and deflections
            self.time_plot = np.arange(len(distancesP)) * np.mean(diff_seconds)
            self.distance_plot = distancesP * 6.45 / 2.5
            plt.figure(0)
            plt.plot(self.time_plot, self.distance_plot)
            plt.plot(self.time_plot, sf(self.distance_plot, 5, 2))
            plt.show()
            plt.figure(1)

            ###
            order_minima = 15
            count_maxima = 5
            ###

            self.normalized_deflection(order_minima, count_maxima)

            diffdistancesP = distancesP[1:] - distancesP[:-1]
        # xdd = np.linspace(0, len(diffdistancesP[:-1])*np.mean(diff_seconds), num = len(diffdistancesP[:-1])*4)
        #    ydd = interp1d(np.arange(len(diffdistancesP))*np.mean(diff_seconds), diffdistancesP, kind='cubic')
        #    plt.subplot(224)
        #    plt.plot( np.arange(len(diffdistancesP))*np.mean(diff_seconds), -diffdistancesP*6.45/5)
        #    plt.plot(xdd,-ydd(xdd)*6.45/5)

        # plt.xlim(0, max(np.arange(len(distancesP)) * np.mean(diff_seconds)))
        # plt.subplot(111)
        # plt.title("Deformation of the tissue")
        # plt.xlabel("Time (s)")
        # plt.ylabel("Tissue length (um)")

        # plt.subplot(224)
        # plt.title("Deformation speed of the tissue")
        # plt.xlabel("Time (s)")
        # plt.ylabel("Speed (um/s)")

        # -------------------------- Frequence plot ---------------------
        # distancesP = (distancesP[2:]+distancesP[1:-1]+distancesP[:-2])/3
        # distancesP = (distancesP[2:]+distancesP[1:-1]+distancesP[:-2])/3

        diffdistancesP = distancesP[1:] - distancesP[:-1]
        y = diffdistancesP[:]
        yint = y[1:] * y[:-1]
        y_filt = [1 if (s < 0 and y[i] < 0) else 0 for i, s in enumerate(yint)]
        tab = []
        for i, item in enumerate(y_filt):
            if item == 1:
                tab.append(i)

        freq = np.array(tab[1:]) - np.array(tab[:-1])

        freq = (freq[2:] + freq[1:-1] + freq[:-2]) / 3
        freq = (freq[2:] + freq[1:-1] + freq[:-2]) / 3
        freq = (freq[2:] + freq[1:-1] + freq[:-2]) / 3

        # plt.subplot(223)
        # plt.plot(np.array(tab[3:-4]), 1/(freq*np.mean(diff_seconds)), "-")

        for track in tracks:
            points = track.points
            if len(points) == 0:
                continue
            print("points", points.shape)
            #    distances = np.linalg.norm(points[:,:] - points[iref,:],axis=1)
            #    distances = signal.detrend(distances)
            distances = abs(points[:, 0] - points[0, 0])
            shape = '-'
            if (points[np.argmax(distances), 0] > points[0, 0]):
                shape = '--'

        # x = np.linspace(0, len(distances[:-1])*np.mean(diff_seconds), num = len(distances[:-1])*2)
        #    y = interp1d(np.arange(len(distances))*np.mean(diff_seconds), distances, kind='cubic')
        #    plt.subplot(221)
        #    plt.plot( np.arange(len(distances))*np.mean(diff_seconds), distances*6.45/5,shape)
        #    plt.plot(x, y(x)*6.45/5,shape)

        plt.xlim(0, max(np.arange(len(distances)) * np.mean(diff_seconds)))
        # plt.title("Deformation of the left (dotted) and right (plain) pillars")
        # plt.xlabel("Time (s)")
        # plt.ylabel("Displacement (um)")
        current_path = os.getcwd()
        current_path.split(os.path.sep)
        folder_name = current_path[-1]
        new_path = os.path.join(current_path[:-1] + "%s.pdf" % folder_name)

        np.save(current_path, [np.arange(len(distancesP)) * np.mean(diff_seconds), distancesP * 6.45 / 2.5])

        plt.savefig(new_path)
        # plt.show()

        F0 = 0

        # -------- Initial parameters -------------
        duration = 0.7
        frequency = 0.3
        sigma = 0.25

        delay = 1 / float(frequency)
        omega = 1 / float(duration)

        # ------------------------2 Functions that creates the shape of the force generator--------------------------

        def f_sin(t, t0):
            if t > 10:
                return 0
            if t < t0:
                return 0
            else:
                t = t - t0
                tr = (t % (delay * 4))
                if (tr < (1 / float(omega)) and tr > 0):
                    if tr < (1 / (3 * float(omega))):
                        return F * np.sin(omega * np.pi * tr) ** (0.001)
                    else:
                        tlim = 1 / (3 * float(omega))
                        tor = np.arcsin((np.sin(omega * np.pi * tlim)) ** (0.001 / 2.5)) / (omega * np.pi)
                        if tr - tlim + tor > duration:
                            return 0
                        else:
                            return F * (np.sin(omega * np.pi * (tr - tlim + tor))) ** 2.5

                else:
                    return 0

        def func_force_source(t):
            return F0 + max(f_sin(t, 0), f_sin(t, delay), f_sin(t, 2 * delay), f_sin(t, 3 * delay))

        # ------------------------Function that returns dy/dt--------------------------
        def func_diff(y, t):
            return (1 / tau * (func_force_source(t) - y))

        # -----------------------Function that returns the numerical solution-------------------------
        def func_solv(t, F_new, duration_new, tau_new):
            global A
            global B
            global C
            global duration
            global F
            global omega
            global tau

            tau = tau_new
            F = F_new
            duration = duration_new
            omega = 1 / float(duration)

            res = np.array(inte.odeint(func_diff, F0, t))
            return res[:, 0]

        t = np.linspace(0, 10, 1000)

        tau = 0.179
        F = 1

        # ------------------ Uncomment here (5 lines) to visualise an example of generator force and corresponding force in the tissue -----------------

        forcesource = [func_force_source(temps) for temps in t]
        forcesol = func_solv(t, F, duration, tau)
        plt.plot(t, forcesource, '--')  # Force of the generator
        plt.plot(t, forcesol)  # Corresponding force in the tissue, solution of the differential equation
        plt.show()

        # -----------------------------------------------------------------------------------------------------------------------------------------------------------
        # -----------------------------------------------------------------------------------------------------------------------------------------------------------
        # -----------------------------------------------------------------------------------------------------------------------------------------------------------
        # ---------------------Displaying section --------------------------------

        path = os.getcwd()
        path2 = path + ".npy"

        data = np.load(path2)  # Load the data from the file in green
        # data = np.load(r'w12.npy') #Load the data from the file in green
        time = data[0]
        distances = data[1]
        distances = - distances + max(distances)  # Reverse the force so the contraction are going up

        diffdist = (distances[1:] - distances[:-1]) / time[1]  # Calculate the speed of contraction

        # ------------- Plot the deflexion of the pillars -------------- Can be commented to avoid having to close this plot when useless
        # plt.plot(time, distances , 'o-k', ms=5, lw =2)
        # plt.xlabel('Time (s)', size = 20)
        # plt.ylabel('Pillar deflexion (um)', size = 20)
        # plt.tick_params(axis='x', labelsize=20)
        # plt.tick_params(axis='y', labelsize=20)
        # plt.show()

        # ------------- Plot the speed of deflexion of the pillars -------------- Can be commented to avoid having to close this plot when useless
        # plt.plot(time[1:], diffdist)
        # plt.xlabel('Time (s)', size = 20)
        # plt.ylabel('Pillar speed of deflexion (um/s)', size = 20)
        # plt.tick_params(axis='x', labelsize=20)
        # plt.tick_params(axis='y', labelsize=20)
        # plt.show()

        # -----------------------------------------------------------------------------------------------------------------------------------------------------------
        # -----------------------------------------------------------------------------------------------------------------------------------------------------------
        # -----------------------------------------------------------------------------------------------------------------------------------------------------------
        # ---------------------Fitting section --------------------------------

        # --------------------Fitting the model to the data----------------------------
        init = 7  # Initial frame for the section and fit
        length = 150  # Length of the window of time points selected for showing the data
        lenfit = 4  # Number of frame/points used for the fit

        frequency = 2  # Expected frequency of the section
        delay = 1 / float(frequency)

        # -------- Selection of the window -------------
        time0 = time[init:init + length]
        time0 = time0 - time0[0]  # Sets the first time point at 0
        distances0 = distances[init:init + length]
        distances0 = distances0 - min(
            distances0)  # Sets the minimum of the section to 0 ----- Can be commented when useful

        # ------------ Vector that attributes a weight to the points for the fit, low is important, high is non important -----------
        pond = np.concatenate((np.linspace(0.1, 0.2, 0), np.linspace(1000, 1001, 100), np.linspace(0.1, 0.2, 150)))

        # ------------- Actual fitting -----------------
        param, paramcov = opt.curve_fit(func_solv, np.array(time0[:lenfit]), np.array(distances0[:lenfit]),
                                        [110, 0.6, 0.06])  # last 3 numbers are initial value for the parameters
        print('F duration tau')  # Print the value of the parameters
        print(param)
        print('maximum deflection');
        print(max(distances))
        pyperclip.copy(str(max(distances)))

        plt.figure(1)
        # plt.title(frequency)
        # plt.plot(time0, distances0, '-', mew=1.5, ms=5)

        # -------- Next line can be uncommented to visualise in red the points selected for the fit
        # plt.plot(time0[:lenfit], func_solv(time0[:lenfit], param[0], param[1], param[2]),'+')

        # -------- Next line can be uncommented to visualise active force generator
        plt.plot(time0, [func_force_source(temps) for temps in time0])

        # -------- Next line can be uncommented to visualise the weight given to each points for the fit
        # plt.plot(time0[:lenfit],pond)

        # plt.axis([-0.1, max(time0), -2, 200])
        # plt.xlabel('Time [s]', size=20)
        # plt.ylabel('Deflection [$\mu m$]', size=20)
        # plt.show()

        # return max(distances)
        print("WHAAAT?!", self.mean_normalized_deflection)
        return (self.mean_normalized_deflection)

    def doTracking(self):
        # get the images
        images = self.db.getImageIterator(start_frame=0)

        # retrieve first image
        image_last = next(images)

        # get points and corresponding tracks
        points = self.db.getMarkers(image=image_last, processed=0)
        p0 = np.array([[point.x, point.y] for point in points if point.track_id]).astype(np.float32)
        tracks = [point.track for point in points if point.track_id]

        # if no tracks are supplied, stop
        if len(tracks) == 0:
            print("Nothing to track")
            return

        # start iterating over all images
        for image in images:
            print("Tracking frame number %d, %d tracks" % (image.sort_index, len(tracks)), image.id, image_last.id)

            # calculate next positions
            p1, st, err = cv2.calcOpticalFlowPyrLK(image_last.data8, image.data8, p0, None, **lk_params)

            # set the new positions
            self.db.setMarkers(image=image, x=p1[:, 0], y=p1[:, 1], processed=0, track=tracks)

            # mark the marker in the last frame as processed
            self.db.setMarkers(image=image_last, x=p0[:, 0], y=p0[:, 1], processed=1, track=tracks)

            # update ClickPoints
            self.cp.reloadMarker(image.sort_index)
            self.cp.jumpToFrameWait(image.sort_index)

            # store positions and image
            p0 = p1
            image_last = image

            # check if we should terminate
            if self.cp.hasTerminateSignal():
                print("Cancelled Tracking")
                sys.exit(0)

    def getTracks(self):
        # -------------------------------------Time---------------------
        images = natsort.natsorted(glob.glob("*.tif"))
        times = []

        for image_path in images:
            times.append(get_meta(image_path))

        diff_times = np.array(times[1:]) - np.array(times[:-1])
        diff_seconds = [d.seconds + d.microseconds / 10 ** 6 for d in diff_times]

        tracks = self.db.getTracks()

        return (tracks, diff_seconds)

    def normalized_deflection(self, order_minima, count_maxima):
        # find local minima in signal, i.e. maximum contractions
        minima = argrelextrema(sf(self.distance_plot, 5, 2), np.less, order=order_minima)[0]
        self.distance_plot = sf(self.distance_plot, 5, 2)
        print(minima)

        # take all deflections and substract the respectively last minimum
        normalized_time = np.array([])
        normalized_distance = np.array([])

        for i in range(len(self.time_plot)):
            for j in minima[::-1]:
                if i >= j:
                    normalized_time = np.append(normalized_time, self.time_plot[i])
                    normalized_distance = np.append(normalized_distance, self.distance_plot[i] - self.distance_plot[j])
                    break
        normalized_distance = sf(normalized_distance, 5, 2)
        minima = argrelextrema(normalized_distance, np.less, order=order_minima)[0]
        minima = np.hstack((0, minima))
        top_values = []
        top_values_norm = []
        for start, stop in zip(minima[:-1], minima[1:]):
            top_values.append(np.sort(normalized_distance[start:stop])[-count_maxima:])
            top_values_norm.append(np.argsort(normalized_distance[start:stop])[-count_maxima:] + start)
        top_values = np.array(top_values)
        top_values_norm = np.array(top_values_norm)

        # get rid of error that appears, when there are too few values before the first minimum
        real_maxima = []
        real_indices = []
        for i in top_values:
            if len(i) == count_maxima:
                real_maxima.append(i)
        self.mean_normalized_deflection = np.mean(real_maxima)

        for i in top_values_norm:
            for j in range(len(i)):
                real_indices.append(i[j])

        # plot
        plt.plot(normalized_time, normalized_distance, '+-')
        plt.plot(normalized_time[real_indices], normalized_distance[real_indices], 'r+')
        plt.plot(normalized_time, np.array([self.mean_normalized_deflection for i in range(len(normalized_time))]))
        plt.plot()
        plt.show()

    def Test(self):
        return (1)