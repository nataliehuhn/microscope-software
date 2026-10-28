@echo off
call "%~dp0Record.bat" -c "Config_Experimental_Copy.txt" %*
exit /b %ERRORLEVEL%
