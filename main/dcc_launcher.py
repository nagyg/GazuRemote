"""
dcc_launcher.py
===============
Launches DCC applications from GazuRemote workfile double-clicks.

Extension routing is defined in DCC_EXTENSIONS – extend here to add
Nuke (.nk), Houdini (.hip), etc.  For each new DCC:
  1. Add its extensions to DCC_EXTENSIONS.
  2. Add a _launch_<dcc>() function following the _launch_nuke() pattern.
  3. Dispatch it in launch_with_dcc().
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Extension → DCC key mapping
# ---------------------------------------------------------------------------

DCC_EXTENSIONS: dict[str, str] = {
    ".comp": "fusion",
    ".nk":   "nuke",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def launch_with_dcc(
    file_path: str,
    config_service,
    app_root: Path,
    log_func=None,
) -> bool:
    """
    Launch the appropriate DCC for *file_path* based on its extension.

    Returns True if a DCC was matched and a launch was attempted.
    Returns False when no DCC handles this extension – the caller can then
    fall back to the default OS open (ui_utils.open_file).
    """
    ext = os.path.splitext(file_path)[1].lower()
    dcc = DCC_EXTENSIONS.get(ext)

    if dcc == "fusion":
        fusion_path = config_service.load_fusion_path()
        _launch_fusion(file_path, fusion_path, app_root, log_func)
        return True

    if dcc == "nuke":
        nuke_path = config_service.load_nuke_path()
        _launch_nuke(file_path, nuke_path, app_root, log_func)
        return True

    return False


# ---------------------------------------------------------------------------
# DCC-specific launchers
# ---------------------------------------------------------------------------

def _launch_fusion(
    file_path: str,
    fusion_path: str,
    app_root: Path,
    log_func=None,
) -> None:
    """Launch Fusion via open_fusion.cmd with FUSION_ROOT injected into env."""

    def _log(msg, color=None):
        if log_func:
            from services import ui_utils
            log_func(msg, color or ui_utils.COLOR_INFO)
        else:
            print(msg)

    cmd_path = Path(app_root) / "dcc" / "Fusion" / "open_fusion.cmd"
    if not cmd_path.exists():
        _log(f"Fusion launch script not found: {cmd_path}", _color("error"))
        return

    env = _get_clean_env()
    env["FUSION_ROOT"] = fusion_path

    _log(f"Launching Fusion: {os.path.basename(file_path)}")

    creationflags = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        subprocess.Popen(
            ["cmd.exe", "/C", str(cmd_path), file_path],
            env=env,
            creationflags=creationflags,
            cwd=str(cmd_path.parent),
        )
    except Exception as exc:
        _log(f"Failed to launch Fusion: {exc}", _color("error"))


def _launch_nuke(
    file_path: str,
    nuke_path: str,
    app_root: Path,
    log_func=None,
) -> None:
    """Launch Nuke via open_nuke.cmd with NUKE_ROOT injected into env."""

    def _log(msg, color=None):
        if log_func:
            from services import ui_utils
            log_func(msg, color or ui_utils.COLOR_INFO)
        else:
            print(msg)

    cmd_path = Path(app_root) / "dcc" / "Nuke" / "open_nuke.cmd"
    if not cmd_path.exists():
        _log(f"Nuke launch script not found: {cmd_path}", _color("error"))
        return

    env = _get_clean_env()
    env["NUKE_ROOT"] = nuke_path

    _log(f"Launching Nuke: {os.path.basename(file_path)}")

    # CREATE_NEW_CONSOLE: visible CMD window for debugging (shows env / script output).
    # /C: window closes automatically after the script finishes (+ timeout in .cmd).
    creationflags = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        subprocess.Popen(
            ["cmd.exe", "/C", str(cmd_path), file_path],
            env=env,
            creationflags=creationflags,
            cwd=str(cmd_path.parent),
        )
    except Exception as exc:
        _log(f"Failed to launch Nuke: {exc}", _color("error"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_clean_env() -> dict[str, str]:
    """
    Build a pristine Windows environment from the Registry so that no
    GazuRemote runtime variables (PYTHONPATH, PySide DLLs, etc.) leak into
    the DCC process.  Falls back to os.environ.copy() on non-Windows.
    """
    if sys.platform != "win32":
        return os.environ.copy()

    import winreg
    import re

    # Volatile keys: generated at logon, not stored in the static registry.
    volatile_keys = [
        "APPDATA", "LOCALAPPDATA", "USERPROFILE", "USERNAME", "USERDOMAIN",
        "COMPUTERNAME", "HOMEDRIVE", "HOMEPATH", "LOGONSERVER",
        "OS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL",
        "PROCESSOR_REVISION", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
        "PUBLIC", "SYSTEMDRIVE", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
        "COMSPEC", "PATHEXT",
    ]
    clean_env: dict[str, str] = {k: os.environ[k] for k in volatile_keys if k in os.environ}

    def _read_reg(hkey, subkey):
        result = {}
        try:
            with winreg.OpenKey(hkey, subkey) as key:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        result[name.upper()] = value
                        i += 1
                    except OSError:
                        break
        except Exception:
            pass
        return result

    system_env = _read_reg(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
    )
    user_env = _read_reg(winreg.HKEY_CURRENT_USER, r"Environment")

    # PATH: system + user concatenated (standard Windows behaviour)
    sys_path = system_env.get("PATH", "")
    usr_path = user_env.get("PATH", "")
    combined_path = f"{sys_path};{usr_path}" if sys_path and usr_path else sys_path or usr_path

    clean_env.update(system_env)
    clean_env.update(user_env)
    if combined_path:
        clean_env["PATH"] = combined_path

    # Expand %VARIABLE% references (two passes for nested refs)
    def _expand(val, env_dict):
        return re.sub(
            r"%([^%]+)%",
            lambda m: str(env_dict.get(m.group(1).upper(), m.group(0))),
            str(val),
        )

    for _ in range(2):
        clean_env = {k: _expand(v, clean_env) for k, v in clean_env.items()}

    return {str(k): str(v) for k, v in clean_env.items()}


def _color(level: str) -> str:
    """Return a ui_utils color constant string without importing at module level."""
    try:
        from services import ui_utils
        return {
            "info":    ui_utils.COLOR_INFO,
            "warning": ui_utils.COLOR_WARNING,
            "error":   ui_utils.COLOR_ERROR,
        }.get(level, ui_utils.COLOR_INFO)
    except ImportError:
        return ""
