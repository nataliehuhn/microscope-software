@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"
python "%~dp0MicroscopeConsole.py" %*
set "console_exit_code=%ERRORLEVEL%"
IF %console_exit_code% NEQ 0 pause
popd
exit /b %console_exit_code%
