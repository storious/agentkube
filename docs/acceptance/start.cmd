@echo off
python -X utf8 "%~dp0experience.py" %*
if errorlevel 1 pause
