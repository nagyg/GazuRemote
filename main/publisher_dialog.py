import os
from pathlib import Path

from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtUiTools import QUiLoader

from services import ui_utils


class PublisherDialog(QtWidgets.QDialog):
    """
    Dialog for publishing a preview file to Kitsu for a given task.
    Allows the user to browse for a local file, set a status and comment.
    """

    def __init__(self, task_data, all_statuses, parent=None):
        super().__init__(parent)

        loader = QUiLoader()
        ui_file_path = os.path.join(os.path.dirname(__file__), "publisher_dialog.ui")
        self.ui = loader.load(ui_file_path, self)

        self.setWindowTitle("Kitsu Publisher")
        self._selected_file_path = None

        # --- Find widgets ---
        self.info_group_box = self.ui.findChild(QtWidgets.QGroupBox, "InfoGroupBox")
        self.file_path_line_edit = self.ui.findChild(QtWidgets.QLineEdit, "filePathLineEdit")
        self.browse_file_button = self.ui.findChild(QtWidgets.QPushButton, "browseFileButton")
        self.status_combo_box = self.ui.findChild(QtWidgets.QComboBox, "status_combo_box")
        self.comment_text_edit = self.ui.findChild(QtWidgets.QTextEdit, "comment_text_edit")
        self.buttonBox = self.ui.findChild(QtWidgets.QDialogButtonBox, "buttonBox")

        missing = [name for name, w in {
            "InfoGroupBox": self.info_group_box,
            "filePathLineEdit": self.file_path_line_edit,
            "browseFileButton": self.browse_file_button,
            "status_combo_box": self.status_combo_box,
            "comment_text_edit": self.comment_text_edit,
            "buttonBox": self.buttonBox,
        }.items() if not w]
        if missing:
            raise RuntimeError(
                f"Could not find required widgets in publisher_dialog.ui: {', '.join(missing)}"
            )

        # --- Task info panel ---
        info_layout = self.info_group_box.layout()
        form_layout = QtWidgets.QFormLayout()

        def add_info_row(label_text, value_text):
            if value_text and value_text != "N/A":
                lbl = QtWidgets.QLabel(f"<b>{label_text}:</b>")
                val = QtWidgets.QLabel(str(value_text))
                val.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
                form_layout.addRow(lbl, val)

        entity_type = task_data.get("entity_type_name")
        if not entity_type or entity_type == "N/A":
            entity_type = task_data.get("task_type_for_entity", "N/A")

        add_info_row("Project", task_data.get("project_name"))
        add_info_row("Episode", task_data.get("episode_name"))
        add_info_row("Sequence", task_data.get("sequence_name"))
        add_info_row(entity_type, task_data.get("entity_name", "N/A"))
        add_info_row("Task", task_data.get("task_type_name"))
        info_layout.addLayout(form_layout)

        # --- Status combo box ---
        current_status_id = task_data.get("task_status_id")
        for status in all_statuses:
            self.status_combo_box.addItem(status["name"], status)
            status_color = status.get("color")
            if status_color:
                idx = self.status_combo_box.count() - 1
                self.status_combo_box.setItemData(
                    idx, QtGui.QColor(status_color), QtCore.Qt.ForegroundRole
                )
            if status["id"] == current_status_id:
                self.status_combo_box.setCurrentIndex(self.status_combo_box.count() - 1)

        # --- Publish button label ---
        ok_btn = self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok)
        if ok_btn:
            ok_btn.setText("Publish")
        ok_btn.setEnabled(False)  # Disabled until a file is selected

        # --- Connect signals ---
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.browse_file_button.clicked.connect(self._on_browse_file)
        self.status_combo_box.currentIndexChanged.connect(self._update_combo_box_color)

        self.setLayout(self.ui.layout())
        self._update_combo_box_color(self.status_combo_box.currentIndex())

    def _on_browse_file(self):
        """Opens a file dialog to select the preview file to publish."""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Preview File",
            str(Path.home()),
            "Media Files (*.mp4 *.mov *.avi *.png *.jpg *.jpeg *.exr *.tiff *.tif *.gif);;All Files (*.*)"
        )
        if file_path:
            self._selected_file_path = file_path
            self.file_path_line_edit.setText(file_path)
            # Enable publish button now that a file is chosen
            ok_btn = self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok)
            if ok_btn:
                ok_btn.setEnabled(True)
            # Set file name as default comment
            file_name = os.path.basename(file_path)
            self.comment_text_edit.setPlainText(file_name)

    def _update_combo_box_color(self, index):
        """Updates the combo box text color to match the selected status color."""
        if index >= 0:
            status = self.status_combo_box.itemData(index)
            if status and isinstance(status, dict):
                color = status.get("color")
                palette = self.status_combo_box.palette()
                font = self.status_combo_box.font()
                if color:
                    qcolor = QtGui.QColor(color)
                    palette.setColor(QtGui.QPalette.Text, qcolor)
                    palette.setColor(QtGui.QPalette.ButtonText, qcolor)
                    palette.setColor(QtGui.QPalette.WindowText, qcolor)
                    font.setBold(True)
                else:
                    palette = QtWidgets.QApplication.palette(self.status_combo_box)
                    font.setBold(False)
                self.status_combo_box.setPalette(palette)
                self.status_combo_box.setFont(font)

    def keyPressEvent(self, event):
        """Ctrl+Enter accepts the dialog; plain Enter allows newlines in comment."""
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and \
                (event.modifiers() & QtCore.Qt.ControlModifier):
            self.accept()
            return
        super().keyPressEvent(event)

    def get_file_path(self):
        """Returns the selected file path, or None if none was chosen."""
        return self._selected_file_path

    def get_comment(self):
        """Returns the comment as HTML-formatted text (newlines → <br>)."""
        plain_text = self.comment_text_edit.toPlainText()
        return ui_utils.format_comment_html(plain_text)

    def get_selected_status(self):
        """Returns the currently selected status dictionary."""
        return self.status_combo_box.currentData()
