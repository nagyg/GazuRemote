import sys
import os
import traceback
from pathlib import Path

from PySide6 import QtWidgets, QtCore
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QObject, Signal, QThread

from services import gazu_api, ui_utils
from services.config_service import ConfigService
from main.main_view import RemoteMainView
from main.version import __version__

# Ensure project root is in path
_project_root = Path(__file__).resolve().parent.parent
if _project_root not in sys.path:
    sys.path.insert(0, str(_project_root))


class LoginWorker(QObject):
    """Background worker for authentication to keep the UI responsive."""
    login_finished = Signal(bool, str)

    def __init__(self, host, username, password):
        super().__init__()
        self.host = host
        self.username = username
        self.password = password

    def run(self):
        try:
            success, message = gazu_api.connect_to_zou(self.host, self.username, self.password)
            self.login_finished.emit(success, message)
        except Exception as e:
            traceback.print_exc()
            self.login_finished.emit(False, str(e))


class RemoteLoginView(QtWidgets.QWidget):
    """
    Login window for GazuRemote.
    Handles authentication, project selection, and mount point validation.
    """

    def __init__(self):
        super().__init__()

        self.setWindowTitle(f"GazuRemote v{__version__}")
        _ico_path = os.path.join(os.path.dirname(__file__), "..", "images", "gazu_remote.ico")
        if os.path.exists(_ico_path):
            self.setWindowIcon(QIcon(_ico_path))

        # --- Load UI ---
        ui_file = os.path.join(os.path.dirname(__file__), "login_window.ui")
        self.ui = QUiLoader().load(ui_file, self)
        if not self.ui:
            print(f"Error: Failed to load UI file: {ui_file}")
            return

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.ui)
        self.setLayout(layout)

        # --- Logo ---
        self.logoLabel = self.ui.findChild(QtWidgets.QLabel, "logoLabel")
        if self.logoLabel:
            image_path = os.path.join(os.path.dirname(__file__), "..", "images", "gazu_remote.svg")
            if os.path.exists(image_path):
                pixmap = QPixmap(image_path)
                self.logoLabel.setPixmap(pixmap.scaledToHeight(100, QtCore.Qt.SmoothTransformation))

        # --- Find Widgets ---
        self.loginButton = self.ui.findChild(QtWidgets.QPushButton, "loginButton")
        self.credButton = self.ui.findChild(QtWidgets.QPushButton, "credButton")
        self.hostLineEdit = self.ui.findChild(QtWidgets.QLineEdit, "hostLineEdit")
        self.userLineEdit = self.ui.findChild(QtWidgets.QLineEdit, "userLineEdit")
        self.passwordLineEdit = self.ui.findChild(QtWidgets.QLineEdit, "passwordLineEdit")
        self.consoleTextEdit = self.ui.findChild(QtWidgets.QTextEdit, "consoleTextEdit")
        self.debugCheckBox = self.ui.findChild(QtWidgets.QCheckBox, "debugCheckBox")
        self.projectComboBox = self.ui.findChild(QtWidgets.QComboBox, "projectComboBox")
        self.projectTypeLineEdit = self.ui.findChild(QtWidgets.QLineEdit, "projectTypeLineEdit")
        self.roleLineEdit = self.ui.findChild(QtWidgets.QLineEdit, "roleLineEdit")
        self.remoteMountPointLineEdit = self.ui.findChild(QtWidgets.QLineEdit, "remoteMountPointLineEdit")
        self.localMountPointLineEdit = self.ui.findChild(QtWidgets.QLineEdit, "localMountPointLineEdit")
        self.browseMountButton = self.ui.findChild(QtWidgets.QPushButton, "browseMountButton")
        self.mountStatusLabel = self.ui.findChild(QtWidgets.QLabel, "mountStatusLabel")

        # --- Initial state ---
        if self.projectComboBox:
            self.projectComboBox.setEnabled(False)
        if self.loginButton:
            self.loginButton.setEnabled(False)
            self.loginButton.setText("Open Remote Project")
        if self.credButton:
            self.credButton.setText("Authenticate")

        # --- Load credentials and config ---
        self.config_service = ConfigService()
        credentials = self.config_service.load_credentials()
        self.last_project_id = credentials.get("last_project_id")

        if credentials:
            if self.hostLineEdit:
                self.hostLineEdit.setText(credentials.get("host", ""))
            if self.userLineEdit:
                self.userLineEdit.setText(credentials.get("user", ""))
            if self.passwordLineEdit:
                self.passwordLineEdit.setText(credentials.get("password", ""))
            if self.debugCheckBox:
                self.debugCheckBox.setChecked(credentials.get("debug", False))

        # --- Internal state ---
        self.thread = None
        self.worker = None
        self.main_window = None
        self._is_logged_in = False
        self.project_data = None

        # --- Connect signals ---
        if self.passwordLineEdit:
            self.passwordLineEdit.setFocus()
            self.passwordLineEdit.returnPressed.connect(self.handle_cred_button_press)
        if self.loginButton:
            self.loginButton.clicked.connect(self.launch_app)
        if self.credButton:
            self.credButton.clicked.connect(self.handle_cred_button_press)
        if self.projectComboBox:
            self.projectComboBox.currentIndexChanged.connect(self.on_project_selection_change)
        if self.browseMountButton:
            self.browseMountButton.clicked.connect(self.on_browse_mount_clicked)
        if self.localMountPointLineEdit:
            self.localMountPointLineEdit.textChanged.connect(self.on_local_mount_changed)

        # --- Auto-login on startup ---
        QtCore.QTimer.singleShot(0, self.try_auto_login_and_fetch_projects)

    def log_to_console(self, message, color=ui_utils.COLOR_INFO):
        """Logs a message to the console with timestamp and color."""
        ui_utils.log_to_widget(self.consoleTextEdit, message, color)

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    def try_auto_login_and_fetch_projects(self):
        """Attempts authentication using stored credentials."""
        host = self.hostLineEdit.text().strip()
        username = self.userLineEdit.text().strip()
        password = self.passwordLineEdit.text().strip()

        if not host or not username or not password:
            self.log_to_console("Please enter credentials and click Authenticate.", ui_utils.COLOR_WARNING)
            if self.credButton:
                self.credButton.setEnabled(True)
            return

        self.log_to_console("Authenticating...", ui_utils.COLOR_INFO)
        if self.credButton:
            self.credButton.setEnabled(False)
        if self.loginButton:
            self.loginButton.setEnabled(False)

        gazu_api.set_debug_mode(self.debugCheckBox.isChecked() if self.debugCheckBox else False)

        self.thread = QThread()
        self.worker = LoginWorker(host, username, password)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.login_finished.connect(self.on_login_finished)
        self.worker.login_finished.connect(self.thread.quit)
        self.worker.login_finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()

    def on_login_finished(self, success, message):
        """Handles the authentication result."""
        if success:
            self._is_logged_in = True

            role_success, role_data = gazu_api.get_user_role()
            role = role_data if role_success else "Unknown"
            if self.roleLineEdit:
                self.roleLineEdit.setText(role)

            self.config_service.save_credentials(
                self.worker.host, self.worker.username, self.worker.password, role
            )

            self.log_to_console(f"Authenticated as {role}. Fetching projects...", ui_utils.COLOR_SUCCESS)
            self._fetch_projects()

            # Make credentials read-only
            if self.hostLineEdit:
                self.hostLineEdit.setReadOnly(True)
            if self.userLineEdit:
                self.userLineEdit.setReadOnly(True)
            if self.passwordLineEdit:
                self.passwordLineEdit.setReadOnly(True)
        else:
            self._is_logged_in = False
            self.log_to_console(f"Login failed: {message}", ui_utils.COLOR_ERROR)
            if self.credButton:
                self.credButton.setEnabled(True)

    # -------------------------------------------------------------------------
    # Project selection
    # -------------------------------------------------------------------------

    def _fetch_projects(self):
        """Fetches open projects and populates the project combo box."""
        projects_success, projects = gazu_api.get_all_open_user_projects()
        if not projects_success or not self.projectComboBox:
            self.log_to_console("Failed to fetch projects.", ui_utils.COLOR_ERROR)
            if self.credButton:
                self.credButton.setEnabled(True)
            return

        # Temporarily disconnect signal
        try:
            self.projectComboBox.currentIndexChanged.disconnect(self.on_project_selection_change)
        except TypeError:
            pass

        current_project_id = None
        if self.projectComboBox.currentIndex() >= 0:
            current_data = self.projectComboBox.currentData()
            if current_data:
                current_project_id = current_data.get("id")
        if not current_project_id:
            current_project_id = self.last_project_id

        self.projectComboBox.clear()
        selected_index = -1
        sorted_projects = sorted(projects, key=lambda p: p.get("name", ""))
        for i, project in enumerate(sorted_projects):
            self.projectComboBox.addItem(project.get("name", "N/A"), project)
            if current_project_id and project.get("id") == current_project_id:
                selected_index = i

        self.projectComboBox.setEnabled(True)
        if selected_index >= 0:
            self.projectComboBox.setCurrentIndex(selected_index)

        # Reconnect signal
        self.projectComboBox.currentIndexChanged.connect(self.on_project_selection_change)

        if self.credButton:
            self.credButton.setEnabled(True)
            self.credButton.setText("Change User")

        self._handle_selected_project()

    def on_project_selection_change(self, index):
        """Handles project combo box selection change."""
        self._handle_selected_project()
        if index >= 0 and self._is_logged_in:
            # Login button only enabled after mount validation
            pass
        else:
            if self.loginButton:
                self.loginButton.setEnabled(False)

    def _handle_selected_project(self):
        """Fetches full project data for the selected project and validates mount points."""
        self.project_data = None
        if self.loginButton:
            self.loginButton.setEnabled(False)

        if not self.projectComboBox or self.projectComboBox.currentIndex() < 0:
            return

        selected_project = self.projectComboBox.currentData()
        if not selected_project:
            return

        success, project_data = gazu_api.get_project_by_id(selected_project.get("id"))
        if not success:
            self.log_to_console(f"Failed to fetch project data: {project_data}", ui_utils.COLOR_ERROR)
            return

        self.project_data = project_data

        # Update production type display
        production_type = project_data.get("production_type", "")
        if self.projectTypeLineEdit:
            self.projectTypeLineEdit.setText(production_type)

        # --- Check that the project is initialized (has a remote mount point in DB) ---
        remote_mountpoint = (project_data.get("data") or {}).get("mountpoint", "")
        if not remote_mountpoint:
            self.log_to_console(
                f"'{project_data.get('name')}' is NOT initialized (no mountpoint in database).",
                ui_utils.COLOR_WARNING
            )
            self._set_mount_status("Project not initialized – no mount point in database.", ui_utils.COLOR_WARNING)
            if self.remoteMountPointLineEdit:
                self.remoteMountPointLineEdit.setText("")
            return

        # Display remote mount point (read-only, from API)
        if self.remoteMountPointLineEdit:
            self.remoteMountPointLineEdit.setText(remote_mountpoint)

        # Load saved local mount point for this project
        project_id = project_data.get("id", "")
        saved_local = self.config_service.load_local_mount_point(project_id)
        if saved_local and self.localMountPointLineEdit:
            self.localMountPointLineEdit.setText(saved_local)

        # Validate mount points
        self._validate_mount_points()

    # -------------------------------------------------------------------------
    # Mount point logic
    # -------------------------------------------------------------------------

    def _validate_mount_points(self):
        """
        Validates the mount point configuration:
        - Remote mount point must be set in the database (project initialized).
        - Local mount point + project name directory must exist on this machine.
        Updates the status label and enables/disables the login button.
        """
        if not self.project_data:
            self._set_mount_status("No project selected.", ui_utils.COLOR_NEUTRAL)
            return

        remote_mountpoint = (self.project_data.get("data") or {}).get("mountpoint", "")
        if not remote_mountpoint:
            self._set_mount_status("Project not initialized – no remote mount point.", ui_utils.COLOR_WARNING)
            if self.loginButton:
                self.loginButton.setEnabled(False)
            return

        project_name = self.project_data.get("name", "")
        local_mount = self.localMountPointLineEdit.text().strip() if self.localMountPointLineEdit else ""

        if not local_mount:
            self._set_mount_status("Please enter the local mount point path.", ui_utils.COLOR_WARNING)
            if self.loginButton:
                self.loginButton.setEnabled(False)
            return

        # Check if local_mount/project_name exists
        local_project_path = Path(local_mount) / project_name

        if local_project_path.exists() and local_project_path.is_dir():
            self._set_mount_status(
                f"✔  Local path found: {local_project_path}",
                ui_utils.COLOR_SUCCESS
            )
            self.log_to_console(
                f"Mount point OK: {local_project_path}",
                ui_utils.COLOR_SUCCESS
            )
            if self.loginButton:
                self.loginButton.setEnabled(True)

            # Save the validated local mount point
            project_id = self.project_data.get("id", "")
            if project_id:
                self.config_service.save_local_mount_point(project_id, local_mount)
        else:
            self._set_mount_status(
                f"⚠  Local path NOT found: {local_project_path}\n"
                f"   Sync the project folder before opening. You can still connect.",
                ui_utils.COLOR_WARNING
            )
            self.log_to_console(
                f"Warning: Local path not found: {local_project_path}",
                ui_utils.COLOR_WARNING
            )
            # Allow opening anyway – user is responsible for sync
            if self.loginButton:
                self.loginButton.setEnabled(True)

    def _set_mount_status(self, message, color):
        """Updates the mount status label text and color."""
        if self.mountStatusLabel:
            self.mountStatusLabel.setText(message)
            self.mountStatusLabel.setStyleSheet(f"color: {color}; font-style: italic;")

    def on_local_mount_changed(self, text):
        """Re-validates mount points when the local mount path changes."""
        self._validate_mount_points()

    def on_browse_mount_clicked(self):
        """Opens a folder browser for selecting the local mount point."""
        current = self.localMountPointLineEdit.text().strip() if self.localMountPointLineEdit else ""
        start_dir = current if current and os.path.exists(current) else str(Path.home())

        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select Local Mount Point",
            start_dir,
            QtWidgets.QFileDialog.ShowDirsOnly | QtWidgets.QFileDialog.DontResolveSymlinks
        )
        if folder and self.localMountPointLineEdit:
            self.localMountPointLineEdit.setText(folder)

    # -------------------------------------------------------------------------
    # Credential management
    # -------------------------------------------------------------------------

    def handle_cred_button_press(self):
        """Handles Authenticate / Change User button."""
        if self._is_logged_in:
            self.logout()
        else:
            self.try_auto_login_and_fetch_projects()

    def logout(self):
        """Logs out and resets the UI."""
        self._is_logged_in = False
        self.project_data = None

        for field in [self.hostLineEdit, self.userLineEdit, self.passwordLineEdit]:
            if field:
                field.setReadOnly(False)

        if self.projectComboBox:
            self.projectComboBox.setEnabled(False)
            self.projectComboBox.clear()
        if self.projectTypeLineEdit:
            self.projectTypeLineEdit.clear()
        if self.roleLineEdit:
            self.roleLineEdit.clear()
        if self.remoteMountPointLineEdit:
            self.remoteMountPointLineEdit.clear()
        if self.loginButton:
            self.loginButton.setEnabled(False)
        if self.credButton:
            self.credButton.setText("Authenticate")

        self._set_mount_status("Select a project to check mount points.", ui_utils.COLOR_NEUTRAL)
        self.log_to_console("Logged out. Please enter credentials.", ui_utils.COLOR_INFO)

    # -------------------------------------------------------------------------
    # Launch
    # -------------------------------------------------------------------------

    def launch_app(self):
        """Launches the RemoteMainView after validation."""
        if not self._is_logged_in or not self.project_data:
            return

        remote_mountpoint = (self.project_data.get("data") or {}).get("mountpoint", "")
        if not remote_mountpoint:
            self.log_to_console(
                "Cannot open project: no mount point set in database.", ui_utils.COLOR_ERROR
            )
            return

        local_mount = self.localMountPointLineEdit.text().strip() if self.localMountPointLineEdit else ""

        # Save last project
        self.config_service.save_last_project(self.project_data.get("id"))

        # Save local mount point
        project_id = self.project_data.get("id", "")
        if project_id and local_mount:
            self.config_service.save_local_mount_point(project_id, local_mount)

        debug_mode = self.debugCheckBox.isChecked() if self.debugCheckBox else False

        credentials = {
            "host": self.hostLineEdit.text() if self.hostLineEdit else "",
            "user": self.userLineEdit.text() if self.userLineEdit else "",
            "role": self.roleLineEdit.text() if self.roleLineEdit else "",
        }

        self.main_window = RemoteMainView(
            debug_mode=debug_mode,
            credentials=credentials,
            project_data=self.project_data,
            local_mount_point=local_mount,
        )

        self.main_window.display()
        self.close()

    def display(self):
        """Shows the login window."""
        self.show()
        ui_utils.center_on_screen(self)
        _ico_path = os.path.join(os.path.dirname(__file__), "..", "images", "gazu_remote.ico")
        if os.path.exists(_ico_path):
            QtCore.QTimer.singleShot(0, lambda: self.setWindowIcon(QIcon(_ico_path)))
