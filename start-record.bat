@echo off
rem Mic3 - use this checkout and its Python environment.
call "%~dp0leica_microscope\Record.bat" %*
exit /b %ERRORLEVEL%
