@echo off
REM =============================================================
REM  GazuRemote – Python312 Setup & Dependency Installer
REM  Run this script ONCE after cloning / updating the repository.
REM =============================================================

SET "SCRIPT_DIR=%~dp0"
SET "PYTHON_DIR=%SCRIPT_DIR%Python312"
SET "PYTHON=%PYTHON_DIR%\python.exe"
SET "PIP=%PYTHON_DIR%\Scripts\pip.exe"
SET "ZIP=%SCRIPT_DIR%Python312.zip"
SET "GAZU_DIR=%SCRIPT_DIR%Python312\Gazu"
SET "GAZU_LIB=%GAZU_DIR%\Lib"

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

echo [ERROR] Python312.zip not found at: %ZIP%
echo         Please re-clone the repository or download the zip manually.
pause
exit /b 1

:install_deps
echo.
echo [INFO] Installing desktop dependencies from requirements.txt...
"%PYTHON%" -m pip install --upgrade pip --quiet --no-warn-script-location
"%PYTHON%" -m pip uninstall -y gazu >nul 2>&1
"%PYTHON%" -m pip install -r "%SCRIPT_DIR%requirements.txt" --no-warn-script-location

IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)

echo.
echo [INFO] Installing Gazu DCC dependencies...
IF EXIST "%GAZU_LIB%" (
    echo [INFO] Removing old Gazu Lib...
    rmdir /s /q "%GAZU_LIB%"
)
mkdir "%GAZU_LIB%"

"%PYTHON%" -m pip install --target "%GAZU_LIB%" -r "%SCRIPT_DIR%requirements_dcc.txt" --no-warn-script-location

IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Gazu DCC dependency installation failed.
    pause
    exit /b 1
)

IF NOT EXIST "%GAZU_LIB%\gazu" (
    echo [ERROR] Gazu package not found after install.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  [OK] GazuRemote is ready. Run GazuRemote.cmd to start.
echo ============================================================
pause
