from __future__ import print_function
from .MicroscopeClient import microscope

def main():
    mic = microscope()
    print("Microscope Console")
    while True:
        try:
            print("> ", end="")
            cmd = raw_input().strip()
            device = int(cmd[:2])
            command = int(cmd[2:5])
            if len(cmd) > 5:
                parameters = cmd[6:]
            else:
                parameters = None
            res = mic.sendCommand(device, command, parameters, wait=True)
            print(res)
        except Exception as err:
            print(err)


if __name__ == "__main__":
    main()
