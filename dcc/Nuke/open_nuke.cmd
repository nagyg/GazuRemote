@echo off
:: NUKE VARS -------------------------------------------------------------
:: NUKE_ROOT is injected by dcc_launcher.py via the process environment.
:: Fallback: used when launched outside GazuRemote.
if not defined NUKE_ROOT set "NUKE_ROOT=C:\Program Files\Nuke17.0v1"

for %%I in ("%~dp0..\..") do set "GAZUREMOTE_ROOT=%%~fI"

:: Profiles
set "HOME=%USERPROFILE%\GazuRemote\dcc\Nuke"
set "NUKE_PLUGINS=%GAZUREMOTE_ROOT%\dcc\Nuke"

:: PYTHON
set "PYTHON_ROOT=%GAZUREMOTE_ROOT%\Python312"

:: GazuLib Python
set "GAZULIB=%PYTHON_ROOT%\Gazu\Lib;%PYTHON_ROOT%\Gazu\scripts"
set "PYTHONPATH=%GAZULIB%"

:: Nuke PATH
:: NUKE_PATH is injected by dcc_launcher.py; only set fallback when launched standalone.
if not defined NUKE_PATH set "NUKE_PATH=%NUKE_PLUGINS%\Gazu;%NUKE_PLUGINS%\Plugins"

:: Nuke exe : "Nuke17.0v1" or "Nuke 17.0v1" -> "Nuke17.0.exe"
for %%I in ("%NUKE_ROOT%") do set "_NUKE_BASENAME=%%~nxI"
for /f "tokens=1 delims=v" %%a in ("%_NUKE_BASENAME%") do set "NUKE_EXE=%%a.exe"
set "NUKE_EXE=%NUKE_EXE: =%"

:: PRINT ---------------------------------------------------------------------
echo ----------------GAZUENV-
echo GAZUREMOTE ROOT        : %GAZUREMOTE_ROOT%
echo HOME                   : %HOME%
echo NUKE PATH              : %NUKE_PATH:;= & ECHO:                       : %
echo PYTHONPATH             : %PYTHONPATH:;= & ECHO:                       : %

echo:
echo Environment DONE, start %NUKE_EXE%
echo:

@REM set

:: RUN -----------------------------------------------------------------------
start "" "%NUKE_ROOT%\%NUKE_EXE%" "%~1"
timeout /t 60 /nobreak
