@echo off
setlocal
chcp 65001 >nul
set "DUB_POWERSHELL=powershell.exe"
where pwsh.exe >nul 2>&1
if not errorlevel 1 set "DUB_POWERSHELL=pwsh.exe"
"%DUB_POWERSHELL%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -Action build %*
set "DUB_EXIT=%errorlevel%"
if not "%DUB_EXIT%"=="0" if not defined DUBFLOW_NO_PAUSE pause
exit /b %DUB_EXIT%
