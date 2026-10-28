@echo off
setlocal
set "BUNDLE=%~dp0"
set "DEFAULT_TARGET=C:\Software\leica_microscope_old"
echo This updates an existing Leica microscope software folder.
echo It backs up the old code first, and preserves the microscope config and calibration.
set /p "TARGET=Software folder to update [%DEFAULT_TARGET%]: "
if "%TARGET%"=="" set "TARGET=%DEFAULT_TARGET%"
if not exist "%BUNDLE%package\leica_microscope\LiveViewer.py" (
  echo Update files are missing. Extract the entire ZIP before running this file.
  pause
  exit /b 1
)
set "DEST=%TARGET%\leica_microscope"
if exist "%DEST%" (
  call :backup_existing
  if errorlevel 1 (
    echo Could not back up the existing software. Update cancelled.
    pause
    exit /b 1
  )
)
robocopy "%BUNDLE%package\leica_microscope" "%DEST%" /E /COPY:DAT /R:2 /W:1 /XD __pycache__ /XF microscope_config.txt projection_velocity_model.json projection_velocity_model_backup_*.json camera.xml camera.mmap
if errorlevel 8 (
  echo Update failed. Your previous software backup is available beside the target folder.
  pause
  exit /b 1
)
echo.
echo Software files copied to: %DEST%
echo The existing microscope_config.txt and projection calibration were preserved.
echo Next run Install_Python_Dependencies.bat in the leica_microscope folder.
echo The first dependency install needs an internet connection.
pause
exit /b 0

:backup_existing
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "STAMP=%%T"
if not defined STAMP exit /b 1
set "BACKUP=%TARGET%\leica_microscope_backup_%STAMP%"
robocopy "%DEST%" "%BACKUP%" /E /COPY:DAT /R:1 /W:1 /XD __pycache__ .venv /XF camera.xml camera.mmap
if errorlevel 8 exit /b 1
exit /b 0
