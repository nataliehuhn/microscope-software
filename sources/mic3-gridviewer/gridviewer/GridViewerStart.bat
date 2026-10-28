@echo off
(echo %1) >> "%appdata%\..\Local\Temp\GridViewer.txt"
start gridviewer_noconsole %1
