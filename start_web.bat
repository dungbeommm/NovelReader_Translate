@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
set "VENV_PY=.venv\Scripts\python.exe"
if not exist "%VENV_PY%" set "VENV_PY=..\..\NovelReader_Translate\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [LOI] Chua co Python virtualenv. Xem README.md de cai dat.
    pause
    exit /b 1
)
for %%D in (data\logs output_text output_audio models\translation models\voices) do if not exist "%%D" mkdir "%%D"
echo Web UI: http://localhost:8000
echo Text: output_text\Ten truyen\
echo Audio: output_audio\Ten truyen\
start "" http://localhost:8000
"%VENV_PY%" -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
pause
