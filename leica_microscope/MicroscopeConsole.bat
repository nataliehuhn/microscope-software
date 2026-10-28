@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "LEICA_REPO_ROOT=%~dp0.."
set "PYTHONPATH=%LEICA_REPO_ROOT%;%PYTHONPATH%"
python "%~dp0MicroscopeConsole.py" %*
set "app_exit_code=%ERRORLEVEL%"
pause
popd
exit /b %app_exit_code%
