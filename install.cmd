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
SET "GAZU_ZIP=%SCRIPT_DIR%Python312\Gazu.zip"
SET "GAZU_DIR=%SCRIPT_DIR%Python312\Gazu"

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
echo [INFO] Refreshing Gazu bundle...
IF NOT EXIST "%GAZU_ZIP%" (
    echo [ERROR] Gazu bundle not found at: %GAZU_ZIP%
    pause
    exit /b 1
)

powershell -NoProfile -Command "if (Test-Path '%GAZU_DIR%\Lib') { Remove-Item '%GAZU_DIR%\Lib' -Recurse -Force }; if (Test-Path '%GAZU_DIR%\scripts') { Remove-Item '%GAZU_DIR%\scripts' -Recurse -Force }"
powershell -NoProfile -Command "Expand-Archive -Path '%GAZU_ZIP%' -DestinationPath '%SCRIPT_DIR%Python312' -Force"

IF NOT EXIST "%GAZU_DIR%\Lib\gazu" (
    echo [ERROR] Gazu bundle extraction failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  [OK] GazuRemote is ready. Run GazuRemote.cmd to start.
echo ============================================================
pause
