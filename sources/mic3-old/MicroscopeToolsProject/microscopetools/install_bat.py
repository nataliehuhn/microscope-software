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
    """ Live Viewer """
    script_path = os.path.join(directory, "LiveViewer.py")
    icon_path = os.path.join(directory, "icons", "LiveViewer.ico")
    with open("LiveViewer.bat", 'w') as fp:
        print("Writing LiveViewer.bat")
        fp.write("@echo off\n")
        fp.write("start "+pythonw+" ")
        fp.write("\""+script_path+"\"\n")
        
    if winshell_imported:
        print("Create desktop shortcut LiveViewer.lnk")
        link_filepath = os.path.join(winshell.desktop(), "LiveViewer.lnk")
        with winshell.shortcut(link_filepath) as link:
          link.path = os.path.abspath("LiveViewer.bat")
          link.working_directory = directory
          link.description = "Live microscope display"
          link.icon_location = (icon_path, 0)
          
    """ Live Viewer (Debug) """
    with open("LiveViewerDebug.bat", 'w') as fp:
        print("Writing LiveViewerDebug.bat")
        fp.write("@echo off\n")
        fp.write("\""+sys.executable+"\" ")
        fp.write("\""+script_path+"\"\n")
        fp.write("IF %ERRORLEVEL% NEQ 0 pause\n")
        
    if winshell_imported:
        print("Create desktop shortcut LiveViewerDebug.lnk")
        link_filepath = os.path.join(winshell.desktop(), "LiveViewer Debug.lnk")
        with winshell.shortcut(link_filepath) as link:
          link.path = os.path.abspath("LiveViewerDebug.bat")
          link.working_directory = directory
          link.description = "Live microscope display (debug)"
          link.icon_location = (icon_path, 0)
          
    """ Record """
    script_path0 = os.path.join(directory, "ConfigCreator", "ConfigCreator.py")
    script_path = os.path.join(directory, "Record.py")
    icon_path = os.path.join(directory, "icons", "Record.ico")
    with open("Record.bat", 'w') as fp:
        print("Writing Record.bat")
        fp.write("@echo off\n")
        fp.write("\""+sys.executable+"\" ")
        fp.write("\""+script_path0+"\" ")
        fp.write("-p \""+script_path+"\"")
        fp.write("-i \""+icon_path+"\"")
        fp.write("\n")
        fp.write("pause\n")
        
    if winshell_imported:
        print("Create desktop shortcut Record.lnk")
        link_filepath = os.path.join(winshell.desktop(), "Record.lnk")
        with winshell.shortcut(link_filepath) as link:
          link.path = os.path.abspath("Record.bat")
          link.working_directory = directory
          link.description = "Record images from microscope"
          link.icon_location = (icon_path, 0)
else:
    pass
        