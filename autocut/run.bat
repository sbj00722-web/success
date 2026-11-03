@echo off
rem Drag video files onto this file to edit them (results go to the output folder).
rem Double-click without a file to open the editor screen instead.
cd /d "%~dp0"
if "%~1"=="" (
    ".venv\Scripts\python.exe" launch.py
) else (
    ".venv\Scripts\python.exe" -m autocut %*
)
pause
