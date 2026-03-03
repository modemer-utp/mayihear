@echo off
setlocal

REM Usage: build-api.bat <GEMINI_API_KEY>
REM Example: build-api.bat AIzaSyYOUR_KEY_HERE

if "%~1"=="" (
    echo ERROR: GEMINI_API_KEY argument is required.
    echo Usage: build-api.bat ^<GEMINI_API_KEY^>
    exit /b 1
)

set GEMINI_API_KEY=%~1
set SCRIPT_DIR=%~dp0
set API_DIR=%SCRIPT_DIR%..\mayihear-api
set RUN_BUILT=%API_DIR%\run_built.py

echo [build-api] Substituting API key into run_built.py...
powershell -NoProfile -Command ^
  "(Get-Content '%API_DIR%\run.py') -replace '__GEMINI_API_KEY_PLACEHOLDER__', '%GEMINI_API_KEY%' | Set-Content '%RUN_BUILT%'"

if errorlevel 1 (
    echo ERROR: Failed to create run_built.py
    exit /b 1
)

echo [build-api] Activating virtual environment...
call "%API_DIR%\.venv\Scripts\activate.bat"
if errorlevel 1 (
    echo ERROR: Could not activate .venv — run: python -m venv .venv ^&^& pip install -r requirements.txt pyinstaller==6.11.1
    exit /b 1
)

echo [build-api] Running PyInstaller...
cd /d "%API_DIR%"
pyinstaller mayihear-api.spec --noconfirm
set PYINSTALLER_EXIT=%errorlevel%

echo [build-api] Cleaning up run_built.py...
del /f /q "%RUN_BUILT%" 2>nul

call deactivate

if %PYINSTALLER_EXIT% neq 0 (
    echo ERROR: PyInstaller failed with exit code %PYINSTALLER_EXIT%
    exit /b %PYINSTALLER_EXIT%
)

echo.
echo [build-api] Done. Binary at: mayihear-api\dist\mayihear-api\mayihear-api.exe
echo [build-api] Verify: mayihear-api\dist\mayihear-api\mayihear-api.exe ^& curl localhost:8000/health

endlocal
