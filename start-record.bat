@echo off
rem Mic2 - use this checkout and its Python environment.
call "%~dp0leica_microscope\Record.bat" %*
exit /b %ERRORLEVEL%
