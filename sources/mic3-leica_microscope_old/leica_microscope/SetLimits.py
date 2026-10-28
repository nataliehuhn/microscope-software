from leica_microscope import Microscope

mic = Microscope(no_camera=True, no_init=True)

# x min
mic.send_command_and_wait("72026 0")
#mic.send_command_and_wait("72026 184655")
# x max
mic.send_command_and_wait("72027 919500")
#mic.send_command_and_wait("72027 910900")
# y min
mic.send_command_and_wait("73026 0")
# y max
mic.send_command_and_wait("73027 600750")
