from __future__ import division
from pylab import *
from PIL import Image
images = []
overlap = 0.1

flatfield = imread("FlatField_002.tif")/3+imread("FlatField_003.tif")/3+imread("FlatField_004.tif")/3
flatfield_mean = mean(flatfield)
flatfield /= flatfield_mean

imageSizeY = 1024
imageSizeX = 1344

array_positions = loadtxt("image_offsets.txt")

total_im = zeros(( ceil(amax(array_positions[:,1]))+imageSizeY,  ceil(amax(array_positions[:,0]))+imageSizeX))

for i,pos in enumerate(array_positions):
    print i
    im = imread("Recording_FoW%d_ModeBF.tif"%i)
    x = int(pos[0])
    y = int(pos[1])
    total_im[y:y+imageSizeY,x:x+imageSizeX] = im/flatfield

#imshow(total_im)
print "Save image"
img2 = Image.fromarray(total_im.astype(uint16),'I;16')
img2.save("total_im.tif")
#imsave("total_im.png",total_im)

print "Image saved"