@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"
python "%~dp0LiveViewer.py" %*
set "viewer_exit_code=%ERRORLEVEL%"
pause
popd
exit /b %viewer_exit_code%
