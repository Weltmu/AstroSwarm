@echo off
chcp 65001 >nul
cd /d "D:\ai\QBotManager"
set PYTHONUTF8=1
".build_venv\Scripts\python.exe" "tools\dev_preview_launcher.py"
if errorlevel 1 pause
