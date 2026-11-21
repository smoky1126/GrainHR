@echo off
cd /d "%~dp0"
python --version >nul 2>&1
if errorlevel 1 (
  echo 這部電腦未安裝 Python。請先安裝 Python 3，然後再雙擊這個檔案。
  pause
  exit /b 1
)
if exist "%~dp0local.bat" call "%~dp0local.bat"
if not defined PYTHONPATH set PYTHONPATH=%~dp0;%~dp0_packages
if not defined PAYROLL_SOURCE set PAYROLL_SOURCE=%PAYROLL_HOME%
if not defined PAYROLL_SOURCE set PAYROLL_SOURCE=%~dp0
set PAYROLL_HOME=%~dp0demo\home
set PAYROLL_DEMO=1
set PIP_USER=0
python -c "from payroll.setup.demo import build_demo; build_demo()"
echo 正在關閉先前的示範...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8502 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { taskkill /F /T /PID $_ }"
timeout /t 1 >nul
python -m streamlit run app\main.py --server.headless false --server.address 127.0.0.1 --browser.serverAddress 127.0.0.1 --server.port 8502 --server.fileWatcherType poll --browser.gatherUsageStats false
pause
