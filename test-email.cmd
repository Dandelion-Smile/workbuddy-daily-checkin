@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0email-tools.ps1" -TestMail
pause
