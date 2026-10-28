LEICA MICROSCOPE SOFTWARE UPDATE BUNDLE (WINDOWS x64, BASLER)

This bundle updates an existing installation such as:
  C:\Software\leica_microscope_old

UPDATE AN EXISTING INSTALLATION
1. Extract the entire ZIP file on the microscope PC.
2. Run Update_Old_Installation.bat.
3. Press Enter to use C:\Software\leica_microscope_old, or type the old
   software folder path when prompted.
4. The updater creates a timestamped backup beside the old software folder,
   then copies the updated code into its leica_microscope subfolder.
5. Run leica_microscope\Install_Python_Dependencies.bat. This creates a local
   Python environment and installs the Basler camera and viewer packages.
   The first install requires an internet connection.
6. Start the software with leica_microscope\live_viewer.bat or
   leica_microscope\Record.bat.

The updater retains the destination PC's microscope_config.txt, any projection
velocity calibration, and generated camera buffers. Keep a copy of the ZIP for
reuse on another PC.

REQUIREMENTS AND HARDWARE SETUP
- Windows 64-bit and Python 3.8–3.12 64-bit. The dependency installer creates
  a private environment so it does not replace packages used by other software.
- The microscope controller must already be installed and reachable by its
  serial COM port. Existing microscope vendor software and drivers are not
  included in this ZIP.
- Install the Basler pylon camera runtime and camera driver from Basler before
  using a Basler camera. The Python binding is installed by the dependency BAT.
- The destination's existing microscope_config.txt is kept. On a fresh PC,
  configure that file for its camera backend, COM port, pixel size, and stage
  range before acquisition.
- Camera and microscope vendor drivers are licensed separately and cannot be
  included in this software-only bundle.

This bundle includes the updated live viewer, recording interface, microscope
controller code, Basler camera backend, and supporting files. Projection
calibration belongs to a specific microscope/camera combination and is kept
from the destination installation instead of being copied from this PC.
