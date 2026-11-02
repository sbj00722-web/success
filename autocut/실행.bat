@echo off
rem Korean messages live in launch.py (cmd.exe misreads UTF-8 text inside .bat files)
cd /d "%~dp0"
".venv\Scripts\python.exe" launch.py
pause
