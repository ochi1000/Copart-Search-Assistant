@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-frontend.ps1" %*
exit /b %ERRORLEVEL%
