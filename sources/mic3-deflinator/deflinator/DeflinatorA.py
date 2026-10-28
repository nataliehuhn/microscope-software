from __future__ import print_function, division
import numpy as np
import clickpoints
from clickpoints import launch
import xlrd
import xlwt
from xlutils.copy import copy
import os
import sys
import glob
from qtpy import QtWidgets

# some magic to prevent Qt5 from swallowing exceptions
def my_excepthook(type, value, tback):
    sys.__excepthook__(type, value, tback)

sys.excepthook = my_excepthook


app = QtWidgets.QApplication(sys.argv)

clickpoints.define_paths()
sys.path.insert(0, os.path.join(os.environ["CLICKPOINTS_PATH"], "addons", "Delfaluation"))
import Delfaluation

a_values = {
    "1:26": 2.44704836e-09,  # mimromanipulator derived factor for 1:26 devices ca. 266 kPa
    "1:22": 3.77667183e-09,  # mimromanipulator derived factor for 1:22 devices ca. 410 kPa
    "1:16": 7.45426753e-09,  # mimromanipulator derived factor for 1:16 devices ca. 810 kPa
    "1:10": 1.33886477e-08,  # mimromanipulator derived factor for 1:10 devices ca. 1454 kPa
}

gel_type = "1:10"
ask_positions = False  # if True lets the user click the starting points for tracking
do_tracking = True

def load_folder(filename):
    book = xlrd.open_workbook(filename, formatting_info=True)
    sh = book.sheet_by_index(0)
    row_headers = []
    for j in range(1, 3 * 6 + 1):
        try:
            row = sh.row(j)
        except IndexError:
            break
        row_headers.append(row[0].value[2:-2])
        print(row[0].value[2:-2])
    return row_headers

def askFolder():
    # the file where to store the previous path
    file_to_store_path = os.path.join(os.path.dirname(__file__), "path.txt")
    # try to retrieve the last selected path
    try:
        with open(file_to_store_path, 'r') as myfile:
            startpath = myfile.read().strip()
    except FileNotFoundError:
        startpath = "."

    # ask the user to select an excel file
    filename = QtWidgets.QFileDialog.getOpenFileName(None, "Save Path", startpath, "*.xls")
    if isinstance(filename, tuple):
        filename = str(filename[0])
    else:
        filename = str(filename)

    # if the used did not select a file, quit the program
    if filename is "":
        print("No folder selected.")
        sys.exit()

    # store the currently selected path (so that the user does not have to navigate to this path the next time)
    folder, name = os.path.split(filename)
    with open(file_to_store_path, "w") as savefile:
        savefile.write(os.path.dirname(folder))

    return filename

def save_deflection(filename, tissues, deflections):
    rb = xlrd.open_workbook(filename, formatting_info=False)
    r_sheet = rb.sheet_by_index(0)  # read only copy to introspect the file
    wb = copy(rb)  # a writable copy (I can't read values out of this, only write to it)
    w_sheet = wb.get_sheet(0)  # the sheet to write to within the writable copy

    # iterate over all tissues (obtained from the folder names)
    for i in range(len(tissues)):
        # iterate over all rows in the table (to find the row with the matching name)
        for j in range(1, 3 * 6 + 1):
            # get the name of the row (and remove * or - from the name)
            try:
                position_name = r_sheet.cell(j, 0).value.strip("*- ")
            except IndexError:
                break

            # get the positions of the bottom, tissue and top
            z_bottom = r_sheet.cell(j, 1).value
            z_tissue = r_sheet.cell(j, 2).value
            z_top = r_sheet.cell(j, 3).value

            if position_name == tissues[i]:
                try:
                    a = a_values[gel_type]
                except KeyError:
                    raise KeyError("Gel type "+gel_type+" not defined")

                # calculate the relevant quantities
                height_tissue = (z_tissue - z_bottom) * 1.33
                height_top = (z_top - z_bottom) * 1.41
                spring_constant = a / (height_tissue * 0.001)**3
                deflection_tissue = deflections[i] * 2 * height_tissue / (3 * height_top - height_tissue)
                active_force = deflection_tissue * spring_constant / 2

                # write the date into the excel table
                w_sheet.write(j, 4, deflections[i])
                w_sheet.write(j, 5, spring_constant)
                w_sheet.write(j, 6, deflection_tissue)
                w_sheet.write(j, 7, active_force)
    # save the excel file
    wb.save(filename)

filename = askFolder()

folder, name = os.path.split(filename)
os.chdir(folder)
headers = load_folder(name)

if ask_positions:
    db = clickpoints.DataFile("evaluation.cdb", "w")
    db.setMarkerType("track", mode=db.TYPE_Normal, color="#FF0000")

    for name in headers:
        print(name)
        try:
            image_name = sorted(glob.glob(os.path.join(name, "*.tif")))[0]
        except IndexError:
            print("ERROR: folder %s not found" % name)
            continue
        print(image_name)
        db.setImage(filename=os.path.join(image_name))

    launch.main(os.path.abspath(db._database_filename))
    do_tracking = True
else:
    db = clickpoints.DataFile("evaluation.cdb", "r")
    launch.main(os.path.abspath(db._database_filename))

max_distances = []
tissues = []

for image in db.getImageIterator():
    os.chdir(image.path.path)
    markers = image.markers
    if do_tracking is True:
        print("Creating new database in folder", os.getcwd())
        db2 = clickpoints.DataFile("clickpoints.cdb", "w")
        print("Add track type")
        type = db2.setMarkerType("track", mode=db.TYPE_Track, color="#FF0000")
        print("Init tracks")
        im2 = db2.setImage(image.filename)
        for m in markers:
            track = db2.setTrack(type)
            db2.setMarkers(image=im2, x=m.x, y=m.y, type=type, processed=0, track=track)
        print("Add all images")
        for image in sorted(glob.glob("*.tif"))[1:]:
            db2.setImage(filename=image)
    else:
        print("Loading database in folder", os.getcwd())
        db2 = clickpoints.DataFile("clickpoints.cdb", "r")
    print("Start delfaluation")
    defl = Delfaluation.Addon(database=db2)

    dist = defl.run(do_tracking=do_tracking)
    #dist =defl.Test()

    print("dist", dist)
    max_distances.append(dist)
    print("max_distances", max_distances)
    tissue = (os.path.split(os.getcwd())[1])
    tissues.append(tissue)
    os.chdir("../..")

save_deflection(filename, tissues, max_distances)
print("max_distances", max_distances)

print("FINISHED")
