@echo off
rem Watches "My Drive\claude_success" on Google Drive: every video put there is edited automatically.
rem Originals move to claude_success\done, results go to claude_success\output.
cd /d "%~dp0"
".venv\Scripts\python.exe" watch_inbox.py %*
pause
