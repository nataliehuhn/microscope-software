import numpy as np
import matplotlib.pyplot as plt
import json

data = np.loadtxt("35mmdish.txt")
xcount = 1
ycount = 1
plate_data = {
    "name": "1 well plate",
    "extent": [],
    "wells": [],
    "well_names": [],
}
output = "plate_data01.json"

well_names_numbers = True

plt.plot(data[:, 0], data[:, 1])
data[:, 1] = data[::-1, 1]
data = data.reshape(-1, 4, 3)

centers_x = (data[:, 1, 0] + data[:, 0, 0]) / 2
centers_y = (data[:, 3, 1] + data[:, 2, 1]) / 2
plt.plot(centers_x, centers_y, "ro")
print(centers_x, centers_y)

widths = data[:, 1, 0] - data[:, 0, 0]
print("widths", widths)
heights = data[:, 3, 1] - data[:, 2, 1]
print("height", heights)

radius = np.mean(np.abs(np.hstack((widths, heights))))

# calculate the "delta_x" and "delta_y" the distance between the center of one well to the center of the next well
# for more than 1 well in x direction, we calculate a delta_x
if xcount != 1:
    delta_x = (centers_x[1] - centers_x[0]) / (xcount - 1)
else:
    delta_x = 0
# for more than 1 well in y direction, we calculate a delta_y
if ycount != 1:
    delta_y = (centers_y[1] - centers_y[0]) / (ycount - 1)
else:
    delta_y = 0


plate_data["extent"] = [centers_x[0]-radius*1.3, centers_x[0]+(xcount-1)*delta_x+radius*1.8,
                        centers_y[0]-radius*1.3, centers_y[0]+(ycount-1)*delta_y+radius*1.3]
#                        centers_y[0]+(ycount-1)*delta_y+radius*1.3, centers_y[0]-radius*1.3]

print("extent", plate_data["extent"])
index = 1
for j in np.arange(ycount-1, -1, -1):
    for i in range(xcount):
        pos_x = centers_x[0] + i*delta_x
        pos_y = centers_y[0] + j*delta_y

        circle1 = plt.Circle((pos_x, pos_y), radius, color='lightgray', ec="gray")
        plate_data["wells"].append([pos_x, pos_y, radius])
        print([pos_x, pos_y, radius])
        plt.gca().add_artist(circle1)
        plt.gca().set_aspect('equal', 'box')
        plt.plot(pos_x, pos_y, "r+")
        if well_names_numbers is True:
            plate_data["well_names"].append(index)
        else:
            plate_data["well_names"].append("ABCDEFGHIJKLM"[ycount-j-1]+str(i+1))
        plt.text(pos_x, pos_y, plate_data["well_names"][-1])
        index += 1


plt.plot(plate_data["extent"][:2], plate_data["extent"][2:], "m-o")

plt.xlim(plate_data["extent"][:2])
plt.ylim(plate_data["extent"][2:])

with open(output, "w") as fp:
    json.dump(plate_data, fp, indent=2)

plt.show()



