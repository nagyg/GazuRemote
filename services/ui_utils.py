import os
import sys
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path

from PySide6 import QtGui, QtWidgets, QtCore

# --- COLOR CONSTANTS ---
COLOR_INFO = "#A5A5A5"
COLOR_SUCCESS = "#008000"
COLOR_WARNING = "#AC7500"
COLOR_ERROR = "#B30600"
COLOR_NEUTRAL = "#888888"
COLOR_DEBUG = "#FF00FF"
COLOR_NEW_TASK = "#14CE14"
COLOR_XFER = "#64B5F6"

WORKFILE_EXTENSIONS = [
    '.ma', '.mb', '.hip', '.blend', '.nk', '.comp', '.aep',
    '.psd', '.psb', '.usd', '.usda', '.usdc', '.usdz',
    '.abc', '.mtlx', '.sdf',
]
HIDDEN_EXTENSIONS = [
    '.autosave', '.autosavet', '.autocomp', '.nk~', '.blend1',
    '.db', '.backup', '.bac', '.bak', '.tmp',
]


def position_next_to_parent(dialog: QtWidgets.QDialog, parent: QtWidgets.QWidget):
    """
    Positions a dialog next to its parent window (right side preferred, then left).
    """
    if not parent:
        return

    parent_window = parent.window()
    main_geo = parent_window.frameGeometry()

    dialog_w = dialog.width()
    dialog_h = dialog.height()

    screen = QtGui.QGuiApplication.screenAt(main_geo.center())
    if not screen:
        screen = QtGui.QGuiApplication.primaryScreen()
    screen_geo = screen.availableGeometry() if screen else None

    if screen_geo:
        space_right = screen_geo.right() - main_geo.right() - 10
        space_left = main_geo.left() - screen_geo.left() - 10

        if dialog_w <= space_right:
            x = main_geo.right() + 10
        elif dialog_w <= space_left:
            x = main_geo.left() - dialog_w - 10
        else:
            x = screen_geo.left() + (screen_geo.width() - dialog_w) // 2
            y = screen_geo.top() + (screen_geo.height() - dialog_h) // 2
            dialog.move(x, y)
            return

        y = main_geo.top()
        y = max(screen_geo.top(), min(y, screen_geo.bottom() - dialog_h))
        dialog.move(x, y)
    else:
        dialog.move(main_geo.right() + 10, main_geo.top())


def center_on_screen(widget: QtWidgets.QWidget):
    """Centers a widget on its active screen."""
    screen = widget.screen()
    if not screen:
        screen = QtGui.QGuiApplication.primaryScreen()

    if screen:
        screen_geometry = screen.availableGeometry()
        widget_geometry = widget.frameGeometry()
        widget_geometry.moveCenter(screen_geometry.center())
        widget.move(widget_geometry.topLeft())


def log_to_widget(text_edit: QtWidgets.QTextEdit, message: str, color: str):
    """Logs a message to a QTextEdit with a timestamp and color."""
    if not text_edit:
        print(f"[LOG] {message}")
        return
    timestamp = datetime.now().strftime("%H:%M:%S")
    colored_message = f'<p style="color:{color}; margin:0;">[{timestamp}] {message}</p>'
    text_edit.append(colored_message)

    scrollbar = text_edit.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())


def format_comment_html(text: str) -> str:
    """Formats a plain text comment for Kitsu (replaces newlines with <br>)."""
    if not text:
        return ""
    return text.replace("\n", "<br>")


def show_in_explorer(file_path: str):
    """Opens the OS file explorer and selects the given file."""
    if not file_path or not os.path.exists(file_path):
        return

    if os.name == "nt":
        subprocess.run(["explorer", "/select,", os.path.normpath(file_path)])
    elif sys.platform == "darwin":
        subprocess.run(["open", "-R", file_path])
    else:
        dir_path = os.path.dirname(file_path)
        webbrowser.open(os.path.realpath(dir_path))


def open_file(file_path: str):
    """Opens a file with the default system application."""
    if not file_path or not os.path.exists(file_path):
        return

    try:
        if sys.platform == "win32":
            cwd = os.path.dirname(os.path.abspath(file_path))
            os.startfile(file_path, cwd=cwd)
        else:
            webbrowser.open(file_path)
    except Exception as e:
        print(f"Could not open file {file_path}: {e}")


def get_kitsu_task_url(base_url, project_id, task_data):
    """
    Generates a Kitsu task/entity URL based on project and task data.
    """
    if not base_url or not project_id or not task_data:
        return None

    entity_type = task_data.get("task_type_for_entity")
    target_url = None

    if entity_type == "Shot":
        task_id = task_data.get("id")
        if task_id:
            target_url = f"{base_url}/productions/{project_id}/shots/tasks/{task_id}"
    elif entity_type == "Asset":
        entity_id = task_data.get("entity_id")
        if entity_id:
            target_url = f"{base_url}/productions/{project_id}/assets/{entity_id}"

    if not target_url:
        target_url = f"{base_url}/productions/{project_id}/shots"

    return target_url


def get_thumbnail_cache_dir() -> Path:
    """Returns the path to the thumbnail cache directory for GazuRemote."""
    cache_dir = Path.home() / "GazuRemote" / "thumbnails"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_thumbnail_path(preview_file_id: str):
    """Returns the Path object for a cached thumbnail image."""
    if not preview_file_id:
        return None
    return get_thumbnail_cache_dir() / f"{preview_file_id}.jpg"
