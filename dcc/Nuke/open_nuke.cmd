@echo off
:: NUKE VARS -------------------------------------------------------------
:: NUKE_ROOT is injected by dcc_launcher.py via the process environment.
:: Fallback: used when launched outside GazuRemote.
if not defined NUKE_ROOT set "NUKE_ROOT=C:\Program Files\Nuke17.0v1"

set GAZUREMOTE_ROOT=%~dp0..\..\

:: Profiles
set HOME=%USERPROFILE%\GazuRemote\dcc\nuke
set NUKE_PLUGINS=%GAZUREMOTE_ROOT%\dcc\Nuke

:: PYTHON
set PYTHON_ROOT=%GAZUREMOTE_ROOT%\Python312

:: GazuLib Python
set GAZULIB=%PYTHON_ROOT%\Gazu\Lib;%PYTHON_ROOT%\Gazu\scripts
set PYTHONPATH=%GAZULIB%;%GAZUREMOTE_ROOT%\dcc\Shared

:: Nuke PATH
set NUKE_PATH=%NUKE_PLUGINS%\Gazu;%NUKE_PLUGINS%\Plugins

:: Nuke exe : "Nuke17.0v1" or "Nuke 17.0v1" -> "Nuke17.0.exe"
for %%I in ("%NUKE_ROOT%") do set "_NUKE_BASENAME=%%~nxI"
for /f "tokens=1 delims=v" %%a in ("%_NUKE_BASENAME%") do set "NUKE_EXE=%%a.exe"
set "NUKE_EXE=%NUKE_EXE: =%"

@REM :: PRINT --------------------------------------------------------------
@REM set

:: RUN ---------------------------------------------------------------------
start "" "%NUKE_ROOT%\%NUKE_EXE%" "%~1"
