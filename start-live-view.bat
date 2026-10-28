@echo off
rem Mic3 - use this checkout and its Python environment.
call "%~dp0leica_microscope\live_viewer.bat" %*
exit /b %ERRORLEVEL%
