@echo off
rem Mic2 - use this checkout and its Python environment.
call "%~dp0leica_microscope\live_viewer.bat" %*
exit /b %ERRORLEVEL%
