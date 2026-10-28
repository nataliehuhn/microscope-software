import os
import clickpoints
from shutil import copyfile

clickpoints.define_paths()

addon_name = "Delfaluation"
addon_path = os.path.join(os.environ["CLICKPOINTS_PATH"], "addons", addon_name)
try:
    os.makedirs(addon_path)
except FileExistsError:
    pass

for file in os.listdir(addon_name):
    if os.path.isfile(os.path.join(addon_name, file)):
        source = os.path.join(addon_name, file)
        target = os.path.join(addon_path, file)
        print(source, target, os.path.exists(target))
        try:
            os.remove(target)
        except:
            pass
        copyfile(source, target)
