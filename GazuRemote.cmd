@echo off
REM =============================================================
REM  GazuRemote Launcher
REM  Uses the local Python312 bundled with this repository.
REM  Run install.cmd first if Python312 is not yet present.
REM =============================================================

SET "SCRIPT_DIR=%~dp0"
SET "PYTHON=%SCRIPT_DIR%Python312\python.exe"

IF NOT EXIST "%PYTHON%" (
    echo [GazuRemote] ERROR: Python312 not found at %PYTHON%
    echo [GazuRemote] Please run install.cmd first.
    pause
    exit /b 1
)

"%PYTHON%" "%SCRIPT_DIR%__main__.py" %*
