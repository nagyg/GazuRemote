@echo off
:: FUSION VARS -------------------------------------------------------------
:: FUSION_ROOT is injected by dcc_launcher.py via the process environment.
:: Fallback: used when launched outside GazuRemote.
if not defined FUSION_ROOT set "FUSION_ROOT=C:\Program Files\Blackmagic Design\Fusion 20"

set GAZUREMOTE_ROOT=%~dp0..\..\

:: Profiles
set GAZUDATA=%~dp0Gazu
set LOCALDATA=%USERPROFILE%\GazuRemote\dcc\fusion

:: PYTHON
set PYTHON_ROOT=%GAZUREMOTE_ROOT%\Python312
set FUSION_PYTHON3_HOME=%PYTHON_ROOT%
set PATH=%PYTHON_ROOT%;%PYTHON_ROOT%\Scripts;%PATH%

:: GazuLib Python
set GAZULIB=%PYTHON_ROOT%\Gazu\Lib;%PYTHON_ROOT%\Gazu\scripts
set PYTHONPATH=%GAZULIB%;%GAZUREMOTE_ROOT%\dcc\Shared;%GAZUDATA%\Python;%PYTHONPATH%

:: Reactor
set REACTOR_INSTALL_PATHMAP=%~dp0
set REACTOR_PATH=%REACTOR_INSTALL_PATHMAP%Reactor

set FUSION_MasterPrefs=%LOCALDATA%\Profiles\Gazu\master.prefs
set FUSION16_PROFILE_DIR=%LOCALDATA%\Profiles
set FUSION16_PROFILE=Gazu

:: Python script updates the preferences file with current environment paths
"%PYTHON_ROOT%\python.exe" "%~dp0setenv_fusion.py" "%GAZUDATA%\Profiles\Gazu\master.prefs" "%FUSION_MasterPrefs%" "GazuData:=%GAZUDATA%" "Reactor:=%REACTOR_PATH%" "LocalData:=%LOCALDATA%"

@REM :: PRINT --------------------------------------------------------------
@REM set

:: RUN ---------------------------------------------------------------------
start "" "%FUSION_ROOT%\Fusion.exe" "%~1"
