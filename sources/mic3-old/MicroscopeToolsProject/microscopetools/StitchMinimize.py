from __future__ import division
from pylab import *
from PIL import Image
import cv2

def getCrossCorr(frameImg, lastframe, method=cv2.TM_CCORR_NORMED):
    res = cv2.matchTemplate(lastframe,frameImg,method)
    return res

mode = 'BF'

countX = 10
countY = 5

save_filename = "Recording_FoW%d_ModeBF.tif"

magnification = 20
sensor_size = 6.45 # um

execfile("config.txt")

imageSizeY = 1024
imageSizeX = 1344

#stageOffsetX = 2823
#stageOffsetY = 2150

StepToMu = 0.1381836
PixToMu = sensor_size/magnification

array_positions = loadtxt("image_offsets.txt")

stageOffsetX = diff(array_positions[:,0])[0]
stageOffsetY = diff(array_positions[:,1])[countX-1]
images = zeros([len(array_positions), imageSizeY, imageSizeX], uint8)
for i in xrange(len(array_positions)):
    images[i] = imread(save_filename%(i,mode))//16
xoffsets = zeros(countX)
yoffsets = zeros(countY)

ion()

print "Stichting X"
for x in xrange(countX-1):
    offset_range = xrange(-60,60)
    errors = zeros(len(offset_range))
    for index,off in enumerate(offset_range):
        xoffsets[x+1] = off

        start1 = stageOffsetX*x*StepToMu/PixToMu+cumsum(xoffsets)[x]
        start2 = stageOffsetX*(x+1)*StepToMu/PixToMu+cumsum(xoffsets)[x+1]
        if start1+imageSizeX > start2:
            overlap_X = start1+imageSizeX-start2
            for y in xrange(countY):
                errors[index] += getCrossCorr(images[x+y*countX,:,-overlap_X:],images[x+1+y*countX,:,:overlap_X])[0,0]#, method=cv2.TM_SQDIFF)
    xoffsets[x+1] = offset_range[ argmax(errors)]
    print argmin(errors), offset_range[ argmax(errors)]
    plot(errors)
    pause(0.01)

print "Stichting Y"
for y in xrange(countY-1):
    offset_range = xrange(-60,60)
    errors = zeros(len(offset_range))
    for index,off in enumerate(offset_range):
        yoffsets[y+1] = off

        start1 = stageOffsetY*y*StepToMu/PixToMu+cumsum(yoffsets)[y]
        start2 = stageOffsetY*(y+1)*StepToMu/PixToMu+cumsum(yoffsets)[y+1]
        if start1+imageSizeY > start2:
            overlap_Y = start1+imageSizeY-start2
            for x in xrange(countX):
                errors[index] += getCrossCorr(images[x+y*countX,-overlap_Y:,:],images[x+(y+1)*countX,:overlap_Y,:])[0,0]#, method=cv2.TM_SQDIFF)
    yoffsets[y+1] = offset_range[ argmax(errors)]
    print argmin(errors), offset_range[ argmax(errors)]
    plot(errors)
    pause(0.01)

print "Putting all together"
total_im = zeros(( stageOffsetY*(countY-1)*StepToMu/PixToMu+sum(yoffsets)+imageSizeY, stageOffsetX*(countX-1)*StepToMu/PixToMu+sum(xoffsets)+imageSizeX), uint16)
for y in xrange(countY):
    for x in xrange(countX):
        start1Y = stageOffsetY*y*StepToMu/PixToMu+cumsum(yoffsets)[y]
        start1X = stageOffsetX*x*StepToMu/PixToMu+cumsum(xoffsets)[x]
        total_im[start1Y:start1Y+imageSizeY,start1X:start1X+imageSizeX] = imread(save_filename%(x+y*countX,mode))

imshow(total_im, cmap='gray')
print "Saving file"
img1 = Image.fromarray(total_im, 'I;16')
img1.save("total_im.tif")
print "Finished"
