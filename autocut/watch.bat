@echo off
rem Watches the inbox folder: every video put there is edited automatically.
rem Originals move to inbox\done, results go to the output folder.
cd /d "%~dp0"
".venv\Scripts\python.exe" watch_inbox.py %*
pause
