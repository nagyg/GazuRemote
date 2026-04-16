import os
import webbrowser
from pathlib import Path

from PySide6 import QtWidgets, QtCore
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QTableView

from services import gazu_api, ui_utils
from services.config_service import ConfigService
from .remote_tasks_widget import RemoteTasksWidget
from .version import __version__


class RemoteMainView(QtWidgets.QMainWindow):
    """
    Main application window for GazuRemote.
    Displays the user's tasks for the selected project.
    No DCC launcher, no scaffold, no file system browser.
    """

    def __init__(self, debug_mode=False, credentials=None, project_data=None, remote_address="", local_address=""):
        super().__init__()
        self.debug_mode = debug_mode
        gazu_api.set_debug_mode(self.debug_mode)

        self.project_data = project_data
        self.remote_address = remote_address
        self.credentials = credentials or {}
        self.config_service = ConfigService()
        self.local_address = local_address or (
            self.config_service.load_local_mount_point(project_data.get("id", ""))
            if project_data else ""
        )
        self.kitsu_base_url = ""
        self.active_publishers = []

        # Resolve GazuRemote root for images
        self._app_root = Path(__file__).resolve().parent.parent

        # Window title
        title = f"GazuRemote v{__version__}"
        if project_data and "name" in project_data:
            title = f"{project_data['name']} — {title}"
        self.setWindowTitle(title)

        _ico = self._app_root / "images" / "gazu_remote.ico"
        if _ico.exists():
            self.setWindowIcon(QIcon(str(_ico)))

        # --- Load UI ---
        ui_file = os.path.join(os.path.dirname(__file__), "main_window.ui")
        self.ui = QUiLoader().load(ui_file, self)
        if not self.ui:
            print(f"Error: Failed to load UI file: {ui_file}")
            return
        self.setCentralWidget(self.ui)

        # --- Find widgets ---
        self.logo_label = self._fw(QtWidgets.QLabel, "logoLabel")
        self.host_line_edit = self._fw(QtWidgets.QLineEdit, "hostLineEdit")
        self.user_line_edit = self._fw(QtWidgets.QLineEdit, "userLineEdit")
        self.role_line_edit = self._fw(QtWidgets.QLineEdit, "roleLineEdit")
        self.remote_mount_line_edit = self._fw(QtWidgets.QLineEdit, "remoteMountLineEdit")
        self.local_mount_line_edit = self._fw(QtWidgets.QLineEdit, "localMountLineEdit")
        self.project_line_edit = self._fw(QtWidgets.QLineEdit, "projectLineEdit")
        self.thumbnail_label = self._fw(QtWidgets.QLabel, "thumbnailLabel")
        self.filter_line_edit = self._fw(QtWidgets.QLineEdit, "filterLineEdit")
        self.status_combo_box = self._fw(QtWidgets.QComboBox, "statusComboBox")
        self.task_type_combo_box = self._fw(QtWidgets.QComboBox, "taskTypeComboBox")
        self.done_combo_box = self._fw(QtWidgets.QComboBox, "doneComboBox")
        self.refresh_button = self._fw(QtWidgets.QPushButton, "refreshButton")
        self.url_button = self._fw(QtWidgets.QPushButton, "urlButton")
        self.publish_button = self._fw(QtWidgets.QPushButton, "publishButton")
        self.tasks_tree_view = self._fw(QtWidgets.QTreeView, "tasksTreeView")
        self.directories_tree_view = self._fw(QtWidgets.QTreeView, "directoriesTreeView")
        self.files_table_view = self._fw(QtWidgets.QTableView, "filesTableView")
        self.console_text_edit = self._fw(QtWidgets.QTextEdit, "consoleTextEdit")

        # --- Setup UI ---
        self._setup_static_ui()
        self._setup_project_context()

    # -------------------------------------------------------------------------
    # Widget finder
    # -------------------------------------------------------------------------

    def _fw(self, widget_type, name):
        """Finds a widget by type and name in the loaded UI."""
        w = self.ui.findChild(widget_type, name)
        if not w and self.debug_mode:
            print(f"Warning: widget '{name}' not found.")
        return w

    # -------------------------------------------------------------------------
    # Static UI setup
    # -------------------------------------------------------------------------

    def _setup_static_ui(self):
        """Sets up read-only fields, combos, and button connections."""

        # Logo
        if self.logo_label:
            svg = self._app_root / "images" / "gazu_remote.svg"
            if svg.exists():
                pix = QPixmap(str(svg))
                self.logo_label.setPixmap(pix.scaledToHeight(56, QtCore.Qt.SmoothTransformation))

        # Credentials
        if self.host_line_edit:
            self.host_line_edit.setText(self.credentials.get("host", ""))
        if self.user_line_edit:
            self.user_line_edit.setText(self.credentials.get("user", ""))
        if self.role_line_edit:
            self.role_line_edit.setText(self.credentials.get("role", ""))

        # Mount points
        if self.remote_mount_line_edit:
            self.remote_mount_line_edit.setText(self.remote_address)
        if self.local_mount_line_edit:
            self.local_mount_line_edit.setText(self.local_address)
        if self.project_line_edit:
            project_name = self.project_data.get("name", "") if self.project_data else ""
            self.project_line_edit.setText(project_name)
            self.project_line_edit.setFocusPolicy(QtCore.Qt.NoFocus)

        # Done combo
        if self.done_combo_box:
            self.done_combo_box.addItems(["Hide", "Visible"])

        # Button connections
        if self.refresh_button:
            self.refresh_button.clicked.connect(self._on_refresh_clicked)
        if self.url_button:
            self.url_button.clicked.connect(self._on_url_button_clicked)
        if self.publish_button:
            self.publish_button.clicked.connect(self._on_publish_clicked)

        # Filter
        if self.filter_line_edit:
            self.filter_line_edit.textChanged.connect(self._on_filter_changed)
            self.filter_line_edit.returnPressed.connect(self._on_filter_changed)

        # Status / task type combo box changes
        if self.status_combo_box:
            self.status_combo_box.currentIndexChanged.connect(self._on_filter_changed)
        if self.task_type_combo_box:
            self.task_type_combo_box.currentIndexChanged.connect(self._on_filter_changed)
        if self.done_combo_box:
            self.done_combo_box.currentIndexChanged.connect(self._on_refresh_clicked)

    # -------------------------------------------------------------------------
    # Project context setup
    # -------------------------------------------------------------------------

    def _setup_project_context(self):
        """Fetches the user's tasks and sets up the task widget."""
        if not self.project_data:
            self.log_to_console("No project data provided.", ui_utils.COLOR_ERROR)
            return

        # Fetch Kitsu base URL for web links
        url_ok, base_url = gazu_api.get_kitsu_base_url()
        if url_ok:
            self.kitsu_base_url = base_url

        # Build the tasks widget
        self.tasks_widget = RemoteTasksWidget(
            tasks_tree_view=self.tasks_tree_view,
            thumbnail_label=self.thumbnail_label,
            project_data=self.project_data,
            directories_tree_view=self.directories_tree_view,
            files_table_view=self.files_table_view,
            remote_address=self.remote_address,
            local_address=self.local_address,
            parent=self,
        )
        self.tasks_widget.task_selection_changed.connect(self._on_task_selection_changed)

        # Load initial task list
        self._load_tasks()

    # -------------------------------------------------------------------------
    # Task loading
    # -------------------------------------------------------------------------

    def _load_tasks(self):
        """Fetches and displays the user's tasks for the current project."""
        self.log_to_console(
            f"Loading tasks for '{self.project_data.get('name', '?')}'...",
            ui_utils.COLOR_INFO
        )

        include_done = (
            self.done_combo_box.currentIndex() == 1
            if self.done_combo_box else False
        )

        user_ok, user = gazu_api.get_logged_in_user()
        if not user_ok:
            self.log_to_console(f"Failed to get logged-in user: {user}", ui_utils.COLOR_ERROR)
            return

        tasks_ok, all_tasks = gazu_api.get_tasks_for_user_and_project(
            user, self.project_data, include_done=include_done
        )
        if not tasks_ok:
            self.log_to_console(f"Failed to fetch tasks: {all_tasks}", ui_utils.COLOR_ERROR)
            return

        self._all_tasks = all_tasks

        # Populate status and task type filter combos
        self._populate_filter_combos(all_tasks)

        # Apply current filters and display
        filtered = self._apply_filters(all_tasks)
        self.tasks_widget.populate_task_view(filtered)

        self.log_to_console(
            f"Loaded {len(filtered)} tasks ({len(all_tasks)} total).",
            ui_utils.COLOR_SUCCESS
        )

    def _populate_filter_combos(self, tasks):
        """Fills status and task-type combo boxes from the fetched task list."""
        if self.status_combo_box:
            prev_status = self.status_combo_box.currentText()
            self.status_combo_box.blockSignals(True)
            self.status_combo_box.clear()
            self.status_combo_box.addItem("All Statuses")
            statuses = sorted({t.get("task_status_name", "") for t in tasks if t.get("task_status_name")})
            self.status_combo_box.addItems(statuses)
            idx = self.status_combo_box.findText(prev_status)
            if idx >= 0:
                self.status_combo_box.setCurrentIndex(idx)
            self.status_combo_box.blockSignals(False)

        if self.task_type_combo_box:
            prev_type = self.task_type_combo_box.currentText()
            self.task_type_combo_box.blockSignals(True)
            self.task_type_combo_box.clear()
            self.task_type_combo_box.addItem("All Types")
            types = sorted({t.get("task_type_name", "") for t in tasks if t.get("task_type_name")})
            self.task_type_combo_box.addItems(types)
            idx = self.task_type_combo_box.findText(prev_type)
            if idx >= 0:
                self.task_type_combo_box.setCurrentIndex(idx)
            self.task_type_combo_box.blockSignals(False)

    def _apply_filters(self, tasks):
        """Filters tasks by the current UI filter selections."""
        result = [t for t in tasks if t.get("task_type_for_entity") in ("Shot", "Asset")]

        # Status filter
        if self.status_combo_box:
            sel = self.status_combo_box.currentText()
            if sel and sel != "All Statuses":
                result = [t for t in result if t.get("task_status_name") == sel]

        # Task type filter
        if self.task_type_combo_box:
            sel = self.task_type_combo_box.currentText()
            if sel and sel != "All Types":
                result = [t for t in result if t.get("task_type_name") == sel]

        # Text filter
        if self.filter_line_edit:
            text = self.filter_line_edit.text().strip().lower()
            if len(text) >= 2:
                result = [
                    t for t in result
                    if text in (t.get("entity_name") or "").lower()
                    or text in (t.get("sequence_name") or "").lower()
                    or text in (t.get("episode_name") or "").lower()
                    or text in (t.get("task_type_name") or "").lower()
                ]

        return result

    # -------------------------------------------------------------------------
    # Slots
    # -------------------------------------------------------------------------

    def _on_refresh_clicked(self):
        """Refreshes the task list from Kitsu and invalidates the template path cache."""
        if hasattr(self, "tasks_widget"):
            self.tasks_widget.refresh_path_map()
        self._load_tasks()

    def _on_filter_changed(self):
        """Re-applies filters without re-fetching from API."""
        if hasattr(self, "_all_tasks"):
            filtered = self._apply_filters(self._all_tasks)
            self.tasks_widget.populate_task_view(filtered)

    def _on_task_selection_changed(self, task_data):
        """Updates the toolbar state based on the selected task."""
        is_task = bool(task_data)
        if self.url_button:
            self.url_button.setEnabled(True)

        # Update thumbnail
        if self.thumbnail_label:
            if is_task:
                self.tasks_widget._show_thumbnail(task_data)
            else:
                self.thumbnail_label.clear()

    def _on_url_button_clicked(self):
        """Opens the current project or task in the Kitsu web interface."""
        project_id = self.project_data.get("id", "") if self.project_data else ""
        # Try to get the selected task
        task_data = self.tasks_widget._get_selected_task() if hasattr(self, "tasks_widget") else None

        url = ui_utils.get_kitsu_task_url(self.kitsu_base_url, project_id, task_data)
        if url:
            webbrowser.open(url)
        else:
            self.log_to_console("Could not build Kitsu URL.", ui_utils.COLOR_WARNING)

    def _on_publish_clicked(self):
        """Toggles the Publisher Manager dialog (show/hide on repeated clicks)."""
        from .publisher_manager_dialog import PublisherManagerDialog
        if not hasattr(self, "publisher_manager_dialog") or self.publisher_manager_dialog is None:
            self.publisher_manager_dialog = PublisherManagerDialog([], self)

        if self.publisher_manager_dialog.isVisible():
            self.publisher_manager_dialog.hide()
        else:
            self.publisher_manager_dialog.show()
            ui_utils.position_next_to_parent(self.publisher_manager_dialog, self)
            self.publisher_manager_dialog.raise_()
            self.publisher_manager_dialog.activateWindow()

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def log_to_console(self, message, color=ui_utils.COLOR_INFO):
        """Logs a message to the embedded console."""
        ui_utils.log_to_widget(self.console_text_edit, message, color)

    # -------------------------------------------------------------------------
    # Display
    # -------------------------------------------------------------------------

    def display(self):
        """Shows the main window centered on screen."""
        self.show()
        ui_utils.center_on_screen(self)
        _ico = self._app_root / "images" / "gazu_remote.ico"
        if _ico.exists():
            QtCore.QTimer.singleShot(0, lambda: self.setWindowIcon(QIcon(str(_ico))))

    def closeEvent(self, event):
        """Cleanup on close."""
        if hasattr(self, "tasks_widget"):
            self.tasks_widget.cleanup()
        super().closeEvent(event)
