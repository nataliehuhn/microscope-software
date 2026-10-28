from leica_microscope import Microscope

def main():
    mic = Microscope(no_camera=True, no_init=True)
    print("Microscope Console")
    while True:
        try:
            print("> ", end="")
            cmd = input().strip()
            res = mic.send_command_and_wait(cmd)
            print(res)
        except Exception as err:
            print(err)


if __name__ == "__main__":
    main()
