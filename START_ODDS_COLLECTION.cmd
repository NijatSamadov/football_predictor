@echo off
cd /d "%~dp0"
echo Football predictor - free odds collection
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python or run odds_collector.py with your Python executable.
  pause
  exit /b 1
)
python odds_collector.py watch
pause
