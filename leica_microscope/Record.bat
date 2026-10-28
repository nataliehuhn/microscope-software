@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"
python "%~dp0ConfigCreator\ConfigCreator.py" -p "%~dp0generate_record.py" -i "%~dp0icons\Record.ico" %*
set "record_exit_code=%ERRORLEVEL%"
pause
popd
exit /b %record_exit_code%
