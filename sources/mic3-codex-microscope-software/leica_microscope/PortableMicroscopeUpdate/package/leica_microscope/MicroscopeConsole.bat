@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "LOCAL_PYTHON=%~dp0.venv\Scripts\python.exe"
if exist "%LOCAL_PYTHON%" (
  set "MICROSCOPE_PYTHON=%LOCAL_PYTHON%"
) else (
  set "MICROSCOPE_PYTHON=python"
)
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"
"%MICROSCOPE_PYTHON%" "%~dp0MicroscopeConsole.py" %*
set "app_exit_code=%ERRORLEVEL%"
if not "%app_exit_code%"=="0" pause
popd
exit /b %app_exit_code%
