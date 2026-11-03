@echo off
rem Watches the claude_success folder: every video put there is edited automatically.
rem Originals move to claude_success\done, results go to the output folder.
cd /d "%~dp0"
".venv\Scripts\python.exe" watch_inbox.py %*
pause
