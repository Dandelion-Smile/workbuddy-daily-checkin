@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0email-tools.ps1"
if errorlevel 1 pause
