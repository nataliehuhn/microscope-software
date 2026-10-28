import sys, os
try:
    import winshell
    winshell_imported = True
except ImportError:
    winshell_imported = False

directory = os.path.dirname(os.path.abspath(__file__))
python = sys.executable
pythonw = python.replace("python.exe", "pythonw.exe")
if sys.platform.startswith('win'):
    """ Camera Server """
    script_path = os.path.join(directory, "CameraServer.py")
    icon_path = os.path.join(directory, "icons", "CameraServer.ico")
    with open("CameraServer.bat", 'w') as fp:
        print("Writing CameraServer.bat")
        fp.write("@echo off\n")
        fp.write("cd "+directory+"\n")
        fp.write("start "+pythonw+" ")
        fp.write("\""+script_path+"\"\n")
        
    if winshell_imported:
        print("Create desktop shortcut CameraServer.lnk")
        link_filepath = os.path.join(winshell.desktop(), "Camera Server.lnk")
        with winshell.shortcut(link_filepath) as link:
          link.path = os.path.abspath("CameraServer.bat")
          link.working_directory = directory
          link.description = "Start camera server"
          link.icon_location = (icon_path, 0)
          link.show_cmd = "min"
          
    """ Camera Server (Debug) """          
    with open("CameraServerDebug.bat", 'w') as fp:
        print("Writing CameraServerDebug.bat")
        fp.write("@echo off\n")
        fp.write("cd "+directory+"\n")
        fp.write("\""+sys.executable+"\" ")
        fp.write("\""+script_path+"\"\n")
        fp.write("IF %ERRORLEVEL% NEQ 0 pause\n")
        
    if winshell_imported:
        print("Create desktop shortcut CameraServer.lnk")
        link_filepath = os.path.join(winshell.desktop(), "Camera Server Debug.lnk")
        with winshell.shortcut(link_filepath) as link:
          link.path = os.path.abspath("CameraServer.bat")
          link.working_directory = directory
          link.description = "Start camera server (debug)"
          link.icon_location = (icon_path, 0)
    
    """ Microscope Server """
    script_path = os.path.join(directory, "MicroscopeServer.py")
    icon_path = os.path.join(directory, "icons", "CameraServer.ico")
    with open("MicroscopeServer.bat", 'w') as fp:
        print("Writing MicroscopeServer.bat")
        fp.write("@echo off\n")
        fp.write("cd "+directory+"\n")
        fp.write("start "+pythonw+" ")
        fp.write("\""+script_path+"\"\n")
        fp.write("IF %ERRORLEVEL% NEQ 0 pause\n")
        
    if winshell_imported:
        print("Create desktop shortcut MicroscopeServer.lnk")
        link_filepath = os.path.join(winshell.desktop(), "Microscope Server.lnk")
        with winshell.shortcut(link_filepath) as link:
          link.path = os.path.abspath("MicroscopeServer.bat")
          link.working_directory = directory
          link.description = "Start microscope server"
          link.icon_location = (icon_path, 0)
          link.show_cmd = "min"
          
    """ Microscope Server (Debug) """
    script_path = os.path.join(directory, "MicroscopeServer.py")
    icon_path = os.path.join(directory, "icons", "CameraServer.ico")
    with open("MicroscopeServerDebug.bat", 'w') as fp:
        print("Writing MicroscopeServerDebug.bat")
        fp.write("@echo off\n")
        fp.write("cd "+directory+"\n")
        fp.write("\""+sys.executable+"\" ")
        fp.write("\""+script_path+"\"\n")
        
    if winshell_imported:
        print("Create desktop shortcut MicroscopeServer.lnk")
        link_filepath = os.path.join(winshell.desktop(), "Microscope Server Debug.lnk")
        with winshell.shortcut(link_filepath) as link:
          link.path = os.path.abspath("MicroscopeServerDebug.bat")
          link.working_directory = directory
          link.description = "Start microscope server (Debug)"
          link.icon_location = (icon_path, 0)   
          
    """ Config.txt """
    if not os.path.exists("Microscope_Config.txt"):
        with open("Microscope_Config.txt", 'w') as fp:
            print("Writing Microscope_Config.txt")
            fp.write("MicroscopeName = \"New Microscope\"\n")
            fp.write("PixelSize = 6.45 # um\n")
            fp.write("Coupler = 1\n")
            fp.write("FlipY = True\n")
            fp.write("Module = ""\n")
            fp.write("Adapter = ""\n")
            fp.write("GainProperty = ""\n")
            fp.write("Width = 200\n")
            fp.write("Height = 100\n")
            fp.write("BitDepth = 16\n")

    if winshell_imported:
        print("Create desktop shortcut Microscope Config.lnk")
        link_filepath = os.path.join(winshell.desktop(), "Microscope Config.lnk")
        with winshell.shortcut(link_filepath) as link:
          link.path = os.path.abspath("Microscope_Config.txt")
          link.working_directory = directory
          link.description = "Configuration of microscope"
else:
    pass
