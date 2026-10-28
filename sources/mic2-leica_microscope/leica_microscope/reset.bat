@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"
python "%~dp0reset.py" %*
set "reset_exit_code=%ERRORLEVEL%"
pause
popd
exit /b %reset_exit_code%
