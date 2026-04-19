"""
app_settings_dialog.py
======================
Application settings dialog for GazuRemote.

Handles user-level configuration stored in ~/GazuRemote/user_config.json.

Variables
---------
  Fusion Path   Directory containing the Fusion executable.
                Default: C:\Program Files\Blackmagic Design\Fusion 20

Extensibility
-------------
To add a new variable:
  1. Add a load_*/save_* method pair to ConfigService.
  2. Call self._make_row() / _make_path_row() / _make_password_row()
     inside the relevant _add_*_section() method (or a new one).
  3. Add the field to _load_values(), _capture_originals(),
     _wire_dirty_checks(), _update_save_state(), and _on_save().
"""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from PySide6.QtGui import QIcon

from services.config_service import ConfigService


# ---------------------------------------------------------------------------
# Styling helpers  (mirrors the Gazu main app style)
# ---------------------------------------------------------------------------

_STYLE_SECTION_HEADER = (
    "font-weight: bold; font-size: 12px; color: #cccccc; "
    "border-bottom: 1px solid #444; padding-bottom: 4px; margin-top: 8px;"
)
_STYLE_USER_BADGE = (
    "font-size: 9px; color: #888; background: #2a3a2a; "
    "border: 1px solid #555; border-radius: 3px; padding: 0 4px;"
)
_STYLE_USER_EDIT = "background: #1e2e1e; color: #c8ffc8;"
_STYLE_WARNING   = "color: #ffcc44; font-size: 10px; font-style: italic;"


# ---------------------------------------------------------------------------
# AppSettingsDialog
# ---------------------------------------------------------------------------

class AppSettingsDialog(QtWidgets.QDialog):
    """
    Centralised application settings dialog for GazuRemote.

    Parameters
    ----------
    config_service : ConfigService   user_config.json backend
    parent         : QWidget | None
    """

    def __init__(
        self,
        config_service: ConfigService,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self._config = config_service

        self.setWindowTitle("Application Settings")
        self.setMinimumWidth(520)
        self.setWindowFlag(QtCore.Qt.Tool)
        self.setModal(True)

        app_icon = QtWidgets.QApplication.windowIcon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        self._build_ui()
        self._load_values()
        self._capture_originals()
        self._wire_dirty_checks()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        from services import ui_utils
        ui_utils.position_next_to_parent(self, self.parentWidget())

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(4)
        root.setContentsMargins(14, 14, 14, 14)

        # -- Form area --------------------------------------------------
        content = QtWidgets.QWidget()
        self._form = QtWidgets.QFormLayout(content)
        self._form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self._form.setRowWrapPolicy(QtWidgets.QFormLayout.DontWrapRows)
        self._form.setSpacing(6)
        self._form.setContentsMargins(0, 0, 0, 0)

        self._add_fusion_section()
        self._add_console_section()
        # Add more sections here: self._add_my_section()

        root.addWidget(content, stretch=1)

        # -- Separator --------------------------------------------------
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setFrameShadow(QtWidgets.QFrame.Sunken)
        root.addWidget(sep)

        # -- Buttons ----------------------------------------------------
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        self._save_btn = btn_box.button(QtWidgets.QDialogButtonBox.Save)
        self._save_btn.setEnabled(False)
        self._cancel_btn = btn_box.button(QtWidgets.QDialogButtonBox.Cancel)
        self._cancel_btn.setDefault(True)
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        root.addWidget(btn_box)

    # ------------------------------------------------------------------
    # Row / section builder helpers  (same pattern as Gazu main app)
    # ------------------------------------------------------------------

    def _section_header(self, title: str) -> None:
        """Add a bold section-header row to the form."""
        lbl = QtWidgets.QLabel(title)
        lbl.setStyleSheet(_STYLE_SECTION_HEADER)
        self._form.addRow(lbl)

    def _badge(self, kind: str) -> QtWidgets.QLabel:
        """Return a small scope-indicator label."""
        lbl = QtWidgets.QLabel("User config")
        lbl.setStyleSheet(_STYLE_USER_BADGE)
        lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        lbl.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        return lbl

    def _make_row(self, label: str, kind: str, placeholder: str = "") -> QtWidgets.QLineEdit:
        """Add a labelled QLineEdit row. Returns the edit widget."""
        edit = QtWidgets.QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setStyleSheet(_STYLE_USER_EDIT)

        row_widget = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row_widget)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.addWidget(edit, stretch=1)
        h.addWidget(self._badge(kind))

        self._form.addRow(label, row_widget)
        return edit

    def _make_path_row(self, label: str, kind: str, placeholder: str = "") -> QtWidgets.QLineEdit:
        """Add a labelled path QLineEdit row with a browse button. Returns the edit widget."""
        edit = QtWidgets.QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setStyleSheet(_STYLE_USER_EDIT)

        browse_btn = QtWidgets.QPushButton("...")
        browse_btn.setFixedWidth(28)
        browse_btn.setToolTip("Browse folder")
        browse_btn.clicked.connect(lambda: self._browse_folder(edit))

        row_widget = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row_widget)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addWidget(edit, stretch=1)
        h.addWidget(browse_btn)
        h.addWidget(self._badge(kind))

        self._form.addRow(label, row_widget)
        return edit

    def _make_password_row(self, label: str, kind: str) -> QtWidgets.QLineEdit:
        """Add a password QLineEdit row with a show/hide toggle. Returns the edit widget."""
        edit = QtWidgets.QLineEdit()
        edit.setEchoMode(QtWidgets.QLineEdit.Password)
        edit.setStyleSheet(_STYLE_USER_EDIT)

        show_btn = QtWidgets.QPushButton("*")
        show_btn.setFixedWidth(28)
        show_btn.setCheckable(True)
        show_btn.setToolTip("Show / hide")
        show_btn.toggled.connect(
            lambda checked: edit.setEchoMode(
                QtWidgets.QLineEdit.Normal if checked else QtWidgets.QLineEdit.Password
            )
        )

        row_widget = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row_widget)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addWidget(edit, stretch=1)
        h.addWidget(show_btn)
        h.addWidget(self._badge(kind))

        self._form.addRow(label, row_widget)
        return edit

    def _browse_folder(self, edit: QtWidgets.QLineEdit) -> None:
        """Generic folder-browse handler shared by all path rows."""
        current = edit.text().strip()
        start = current if current else "C:\\"
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Directory", start, QtWidgets.QFileDialog.ShowDirsOnly
        )
        if chosen:
            edit.setText(chosen)

    def _make_checkbox_row(self, label: str, kind: str, description: str = "") -> QtWidgets.QCheckBox:
        """Add a labelled QCheckBox row. Returns the checkbox widget."""
        checkbox = QtWidgets.QCheckBox(description)

        row_widget = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row_widget)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.addWidget(checkbox)
        h.addStretch()
        h.addWidget(self._badge(kind))

        lbl = QtWidgets.QLabel(label)
        lbl.setMinimumWidth(110)
        lbl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self._form.addRow(lbl, row_widget)
        return checkbox

    # ------------------------------------------------------------------
    # Section builders  - one method per logical group
    # ------------------------------------------------------------------

    def _add_fusion_section(self) -> None:
        self._section_header("Fusion")
        self._fusion_path_edit = self._make_path_row(
            "Root Path", "user",
            placeholder=r"C:\Program Files\Blackmagic Design\Fusion 20",
        )

    def _add_console_section(self) -> None:
        self._section_header("Console")
        self._show_console_checkbox = self._make_checkbox_row(
            "Show Console", "user",
            description="Show cmd window on DCC launch",
        )

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def _load_values(self) -> None:
        self._fusion_path_edit.setText(self._config.load_fusion_path())
        self._show_console_checkbox.setChecked(self._config.load_show_dcc_console())

    def _capture_originals(self) -> None:
        """Snapshot the loaded values so we can detect dirty state."""
        self._orig_fusion_path = self._fusion_path_edit.text()
        self._orig_show_console = self._show_console_checkbox.isChecked()

    def _wire_dirty_checks(self) -> None:
        self._fusion_path_edit.textChanged.connect(self._update_save_state)
        self._show_console_checkbox.toggled.connect(self._update_save_state)

    def _update_save_state(self) -> None:
        dirty = (
            self._fusion_path_edit.text() != self._orig_fusion_path
            or self._show_console_checkbox.isChecked() != self._orig_show_console
        )
        self._save_btn.setEnabled(dirty)

    def _on_save(self) -> None:
        self._config.save_fusion_path(self._fusion_path_edit.text().strip())
        self._config.save_show_dcc_console(self._show_console_checkbox.isChecked())
        self.accept()