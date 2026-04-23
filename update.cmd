@echo off
:: UPDATE GazuRemote – pulls latest master from origin
setlocal

for %%I in ("%~dp0.") do set "REPO_ROOT=%%~fI"

echo ----------------GAZUREMOTE UPDATE-
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
    echo ERROR: %REPO_ROOT% is not a git repository.
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
