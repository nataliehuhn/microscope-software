@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "VENV=%~dp0.venv"
if exist "%VENV%\Scripts\python.exe" goto check_python
where py >nul 2>&1
if not errorlevel 1 (
  for %%V in (3.11 3.10 3.12 3.9 3.8) do (
    py -%%V -m venv "%VENV%" >nul 2>&1
    if exist "%VENV%\Scripts\python.exe" goto check_python
  )
)
python -m venv "%VENV%" >nul 2>&1
if not exist "%VENV%\Scripts\python.exe" (
  echo Python 3.8 to 3.12, 64-bit, is required. Install it and run this again.
  echo Keep the Python Launcher for Windows option enabled during installation.
  pause
  exit /b 1
)
:check_python
"%VENV%\Scripts\python.exe" -c "import struct,sys; sys.exit(0 if struct.calcsize('P') == 8 and (3,8) <= sys.version_info[:2] <= (3,12) else 1)"
if errorlevel 1 (
  echo This package needs 64-bit Python 3.8 to 3.12.
  pause
  exit /b 1
)
:install_packages
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto failed
"%VENV%\Scripts\python.exe" -m pip install -r "%~dp0requirements-basler-windows.txt"
if errorlevel 1 goto failed
echo.
echo Python dependencies installed. Run live_viewer.bat or Record.bat.
popd
pause
exit /b 0
:failed
echo Dependency installation failed. Check the internet connection and error above.
popd
pause
exit /b 1
