@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
set "VENV_PY=.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [LOI] Chua co Python virtualenv.
    pause
    exit /b 1
)
echo ========================================================
echo  KHOI DONG SCRIPT SAN VPS ORACLE CLOUD (SINGAPORE)
echo ========================================================
"%VENV_PY%" scripts\hunt_vps.py
pause
