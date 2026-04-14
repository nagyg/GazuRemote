@echo off
REM =============================================================
REM  GazuRemote – Python312 Setup & Dependency Installer
REM  Run this script ONCE after cloning / updating the repository.
REM =============================================================

SET "SCRIPT_DIR=%~dp0"
SET "PYTHON_DIR=%SCRIPT_DIR%Python312"
SET "PYTHON=%PYTHON_DIR%\python.exe"
SET "PIP=%PYTHON_DIR%\Scripts\pip.exe"

echo ============================================================
echo  GazuRemote Installer
echo ============================================================
echo.

REM --- Check if Python312 folder already exists ---
IF EXIST "%PYTHON%" (
    echo [OK] Python found at: %PYTHON%
    goto :install_deps
)

echo [INFO] Python312 not found in: %PYTHON_DIR%
echo.
echo  Option A: Copy the bundled Python from the main Gazu installation.
echo            Source: %%WORKGROUP%%\Gazu\Python312
echo.
echo  Option B: Download Python 3.12 from https://www.python.org/downloads/
echo            and install it into the Python312 subfolder of this directory.
echo.

REM --- Try to copy from sibling Gazu installation ---
IF DEFINED WORKGROUP (
    SET "GAZU_PYTHON=%WORKGROUP%\Gazu\Python312"
    IF EXIST "%GAZU_PYTHON%\python.exe" (
        echo [INFO] Found Gazu Python at: %GAZU_PYTHON%
        echo [INFO] Copying to: %PYTHON_DIR%
        xcopy /E /I /Y "%GAZU_PYTHON%" "%PYTHON_DIR%"
        echo [OK] Python copied successfully.
        goto :install_deps
    )
)

echo [ERROR] Could not locate Python312. Please install manually (see instructions above).
echo         Then re-run this script.
pause
exit /b 1

:install_deps
echo.
echo [INFO] Installing / updating dependencies from requirements.txt...
"%PIP%" install --upgrade pip --quiet
"%PIP%" install -r "%SCRIPT_DIR%requirements.txt"

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
