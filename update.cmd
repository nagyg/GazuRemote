@echo off
:: UPDATE GazuRemote – pulls latest master from origin
setlocal

for %%I in ("%~dp0.") do set "REPO_ROOT=%%~fI"

echo -------------------------------------------------------------------GAZUREMOTE UPDATE-
echo Repository : %REPO_ROOT%
echo:

cd /d "%REPO_ROOT%"

:: Verify git is installed
where git >nul 2>&1
if errorlevel 1 (
    echo ERROR: git is not installed or not on PATH.
    echo:
    echo Please download and install Git for Windows:
    echo   https://git-scm.com/download/win
    echo:
    echo After installation, re-run this script.
    pause
    exit /b 1
)

:: Verify this is a git repo
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo ERROR: This folder is not a git repository.
    echo:
    echo It looks like GazuRemote was downloaded as a ZIP archive.
    echo ZIP downloads cannot be updated with git pull.
    echo:
    echo To enable automatic updates, clone the repository instead:
    echo:
    echo   1. Delete or rename this folder
    echo   2. Run:  cd ~\Downloads
    echo   3. Run:  git clone https://github.com/nagyg/GazuRemote.git ./GazuRemote
    echo   4. Run:  install.cmd
    echo   5. Run:  update.cmd to update in the future
    echo:
    pause
    exit /b 1
)

:: Show current state
echo Current branch:
git branch --show-current

echo:
echo Fetching origin...
git fetch origin

echo:
echo Pulling latest master...
git pull origin master

echo:
if errorlevel 1 (
    echo ERROR: git pull failed. Check output above.
) else (
    echo Update complete.
)

echo:
pause
endlocal
