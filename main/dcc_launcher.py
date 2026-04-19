"""
dcc_launcher.py
===============
Launches DCC applications from GazuRemote workfile double-clicks.

Extension routing is defined in DCC_EXTENSIONS – extend here to add
Nuke (.nk), Houdini (.hip), etc.  For each new DCC:
  1. Add its extensions to DCC_EXTENSIONS.
  2. Add a _launch_<dcc>() function following the _launch_fusion() pattern.
  3. Dispatch it in launch_with_dcc().
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


# ---------------------------------------------------------------------------
# Extension → DCC key mapping
# ---------------------------------------------------------------------------

DCC_EXTENSIONS: dict[str, str] = {
    ".comp": "fusion",
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
        show_console = config_service.load_show_dcc_console()
        _launch_fusion(file_path, fusion_path, app_root, show_console, log_func)
        return True

    return False


# ---------------------------------------------------------------------------
# DCC-specific launchers
# ---------------------------------------------------------------------------

def _launch_fusion(
    file_path: str,
    fusion_path: str,
    app_root: Path,
    show_console: bool = True,
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

    # Inject FUSION_ROOT so open_fusion.cmd uses the user-configured path
    env = os.environ.copy()
    env["FUSION_ROOT"] = fusion_path

    _log(f"Launching Fusion: {os.path.basename(file_path)}")

    creationflags = (
        subprocess.CREATE_NEW_CONSOLE if show_console
        else subprocess.CREATE_NO_WINDOW
    ) | subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        subprocess.Popen(
            ["cmd.exe", "/C", str(cmd_path), file_path],
            env=env,
            creationflags=creationflags,
            cwd=str(cmd_path.parent),
        )
    except Exception as exc:
        _log(f"Failed to launch Fusion: {exc}", _color("error"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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
