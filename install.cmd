@echo off
REM =============================================================
REM  GazuRemote – Python312 Setup & Dependency Installer
REM  Run this script ONCE after cloning / updating the repository.
REM =============================================================

SET "SCRIPT_DIR=%~dp0"
SET "PYTHON_DIR=%SCRIPT_DIR%Python312"
SET "PYTHON=%PYTHON_DIR%\python.exe"
SET "PIP=%PYTHON_DIR%\Scripts\pip.exe"
SET "ZIP=%SCRIPT_DIR%Python312_clean.zip"

echo ============================================================
echo  GazuRemote Installer
echo ============================================================
echo.

REM --- Check if Python312 folder already exists ---
IF EXIST "%PYTHON%" (
    echo [OK] Python found at: %PYTHON%
    goto :install_deps
)

echo [INFO] Python312 not found. Extracting bundled environment...

REM --- Extract from bundled zip ---
IF EXIST "%ZIP%" (
    powershell -NoProfile -Command "Expand-Archive -Path '%ZIP%' -DestinationPath '%PYTHON_DIR%' -Force"
    IF EXIST "%PYTHON%" (
        echo [OK] Python extracted to: %PYTHON_DIR%
        goto :install_deps
    ) ELSE (
        echo [ERROR] Extraction failed.
        pause
        exit /b 1
    )
)

echo [ERROR] Python312_clean.zip not found at: %ZIP%
echo         Please re-clone the repository or download the zip manually.
pause
exit /b 1

:install_deps
echo.
echo [INFO] Installing dependencies from requirements.txt...
"%PYTHON%" -m pip install --upgrade pip --quiet
"%PYTHON%" -m pip install -r "%SCRIPT_DIR%requirements.txt"

IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  [OK] GazuRemote is ready. Run GazuRemote.cmd to start.
echo ============================================================
pause
