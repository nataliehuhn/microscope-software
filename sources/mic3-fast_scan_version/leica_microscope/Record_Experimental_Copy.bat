@echo off
setlocal
rem Launch the record GUI and generated scripts from this isolated copy.
set "LEICA_REPO_ROOT=%~dp0.."
set "PYTHONPATH=%LEICA_REPO_ROOT%;%PYTHONPATH%"
python "%~dp0ConfigCreator\ConfigCreator.py" -c "Config_Experimental_Copy.txt" -p "%~dp0generate_record.py" -i "%~dp0icons\Record.ico"
pause
