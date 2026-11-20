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
if not defined PAYROLL_HOME set PAYROLL_HOME=%~dp0
set PIP_USER=0
if not exist "%~dp0_packages\streamlit\__init__.py" if not exist "%PYTHONPATH%\streamlit\__init__.py" (
  echo 正在安裝 GrainHR，請稍候...
  python -m pip install --target "%~dp0_packages" --no-cache-dir -r "%~dp0requirements.txt"
)
echo 正在關閉先前的 GrainHR...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { taskkill /F /T /PID $_ }"
timeout /t 1 >nul
start "" cmd /c "timeout /t 4 >nul & start http://localhost:8501"
python -m streamlit run app\main.py --server.headless true --server.port 8501 --server.fileWatcherType poll
pause
