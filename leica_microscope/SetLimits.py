"""Apply this microscope's configured XY limits without moving the stage."""
from leica_microscope import Microscope


def main():
    mic = Microscope(no_camera=True, no_init=True)
    for command, setting in (("72026", "stage_min_x"),
                             ("72027", "stage_max_x"),
                             ("73026", "stage_min_y"),
                             ("73027", "stage_max_y")):
        mic.send_command_and_wait("{} {}".format(command, int(mic.config[setting])))


if __name__ == "__main__":
    main()
