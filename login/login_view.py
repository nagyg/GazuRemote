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


class PathCheckWorker(QObject):
    """Checks if a remote path (UNC or local) is accessible without blocking the UI."""
    finished = Signal(bool, str)  # (accessible, path_checked)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        try:
            accessible = Path(self.path).is_dir()
            self.finished.emit(accessible, self.path)
        except Exception:
            self.finished.emit(False, self.path)


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
        layout.addWidget(self.ui)
        self.setLayout(layout)

        # --- Logo ---
        self.logoLabel = self.ui.findChild(QtWidgets.QLabel, "logoLabel")
        if self.logoLabel:
            image_path = os.path.join(os.path.dirname(__file__), "..", "images", "gazu_remote.svg")
            if os.path.exists(image_path):
                pixmap = QPixmap(image_path)
                self.logoLabel.setPixmap(pixmap.scaledToHeight(128, QtCore.Qt.SmoothTransformation))

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
        self.remoteAddressLineEdit = self.ui.findChild(QtWidgets.QLineEdit, "remoteAddressLineEdit")
        self.refreshMountButton = self.ui.findChild(QtWidgets.QPushButton, "refreshPushButton")

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
        self._path_check_thread = None
        self._path_check_worker = None
        self._remote_path_check_thread = None
        self._remote_path_check_worker = None
        self.main_window = None
        self._is_logged_in = False
        self.project_data = None

        # Debounce timer: waits 400 ms after last keystroke before starting path check
        self._path_check_debounce = QtCore.QTimer(self)
        self._path_check_debounce.setSingleShot(True)
        self._path_check_debounce.timeout.connect(self._validate_mount_points)

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
        if self.remoteAddressLineEdit:
            self.remoteAddressLineEdit.textChanged.connect(self._on_remote_address_text_changed)
            self.remoteAddressLineEdit.returnPressed.connect(self._validate_mount_points)
        if self.refreshMountButton:
            self.refreshMountButton.clicked.connect(self._validate_mount_points)

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
            if self.remoteMountPointLineEdit:
                self.remoteMountPointLineEdit.setText("")
            return

        # Display remote mount point (read-only, from API)
        if self.remoteMountPointLineEdit:
            self.remoteMountPointLineEdit.setText(remote_mountpoint)

        # Load saved remote address for this project (block signal to avoid double validation)
        project_id = project_data.get("id", "")
        project_name = project_data.get("name", "")
        saved_address = self.config_service.load_remote_address(project_id)
        # Normalise: strip trailing project-name segment if mistakenly included
        if project_name and saved_address:
            normalised = saved_address.rstrip("\\/")
            if normalised.lower().endswith(os.sep + project_name.lower()) or \
               normalised.lower().endswith("/" + project_name.lower()):
                saved_address = normalised[: -(len(os.sep) + len(project_name))]
                self.config_service.save_remote_address(project_id, saved_address)
        if self.remoteAddressLineEdit:
            self.remoteAddressLineEdit.blockSignals(True)
            self.remoteAddressLineEdit.setText(saved_address)
            self.remoteAddressLineEdit.blockSignals(False)

        # Single explicit validation
        self._validate_mount_points()

    # -------------------------------------------------------------------------
    # Mount point logic
    # -------------------------------------------------------------------------

    def _validate_mount_points(self):
        """
        Validates the mount point configuration:
        - DB mountpoint (local mapped drive, e.g. Z:\\Projects) must exist locally.
          Confirms the drive mapping is active and the project folder is accessible.
        - Server address (remoteAddressLineEdit, VPN UNC) is optional at this stage
          but saved when provided.
        """
        if not self.project_data:
            if self.loginButton:
                self.loginButton.setEnabled(False)
            return

        local_mount = (self.project_data.get("data") or {}).get("mountpoint", "")
        if not local_mount:
            self.log_to_console(
                "Project not initialized – no mount point set in the database.",
                ui_utils.COLOR_WARNING
            )
            if self.loginButton:
                self.loginButton.setEnabled(False)
            return

        project_name = self.project_data.get("name", "")
        local_project_path = str(Path(local_mount) / project_name)

        # Disable login during async path check
        if self.loginButton:
            self.loginButton.setEnabled(False)
        if self.refreshMountButton:
            self.refreshMountButton.setEnabled(False)

        # Stop debounce in case we were called directly
        self._path_check_debounce.stop()

        # Cancel any previous check still running
        if self._path_check_thread is not None:
            try:
                if self._path_check_thread.isRunning():
                    self._path_check_thread.quit()
                    self._path_check_thread.wait(1000)
            except RuntimeError:
                pass
            self._path_check_thread = None
            self._path_check_worker = None

        self.log_to_console(
            f"Checking local mapped path: {local_project_path} ...",
            ui_utils.COLOR_INFO
        )

        self._path_check_thread = QThread()
        self._path_check_worker = PathCheckWorker(local_project_path)
        self._path_check_worker.moveToThread(self._path_check_thread)

        self._path_check_thread.started.connect(self._path_check_worker.run)
        self._path_check_worker.finished.connect(self._on_path_check_finished)
        self._path_check_worker.finished.connect(self._path_check_thread.quit)
        self._path_check_worker.finished.connect(self._path_check_worker.deleteLater)
        self._path_check_thread.finished.connect(self._path_check_thread.deleteLater)
        self._path_check_thread.finished.connect(self._clear_path_check_thread)

        self._path_check_thread.start()

    def _clear_path_check_thread(self):
        """Clears the thread reference after it has been deleted by Qt."""
        self._path_check_thread = None

    def _clear_remote_path_check_thread(self):
        """Clears the remote thread reference after it has been deleted by Qt."""
        self._remote_path_check_thread = None

    def _on_path_check_finished(self, accessible, path_checked):
        """Called when the background local path accessibility check completes."""
        if not accessible:
            self.log_to_console(
                f"✖  Local mapped path NOT accessible: {path_checked}",
                ui_utils.COLOR_ERROR
            )
            if self.loginButton:
                self.loginButton.setEnabled(False)
            if self.refreshMountButton:
                self.refreshMountButton.setEnabled(True)
            return

        self.log_to_console(
            f"✔  Local path accessible: {path_checked}",
            ui_utils.COLOR_SUCCESS
        )

        # Save confirmed local mount
        if self.project_data:
            project_id = self.project_data.get("id", "")
            local_mount = (self.project_data.get("data") or {}).get("mountpoint", "")
            if project_id and local_mount:
                self.config_service.save_local_mount_point(project_id, local_mount)

        # Now validate remote address if provided
        remote_address = self.remoteAddressLineEdit.text().strip() if self.remoteAddressLineEdit else ""
        if not remote_address:
            # Remote address is required — do not allow opening without it
            self.log_to_console(
                "Server Address is required. Please enter the remote server path.",
                ui_utils.COLOR_WARNING
            )
            if self.loginButton:
                self.loginButton.setEnabled(False)
            if self.refreshMountButton:
                self.refreshMountButton.setEnabled(True)
            return

        # Cancel any previous remote check
        if self._remote_path_check_thread is not None:
            try:
                if self._remote_path_check_thread.isRunning():
                    self._remote_path_check_thread.quit()
                    self._remote_path_check_thread.wait(1000)
            except RuntimeError:
                pass
            self._remote_path_check_thread = None
            self._remote_path_check_worker = None

        project_name = self.project_data.get("name", "") if self.project_data else ""
        remote_project_path = str(Path(remote_address) / project_name) if project_name else remote_address
        self.log_to_console(
            f"Checking remote project path: {remote_project_path} ...",
            ui_utils.COLOR_INFO
        )

        self._remote_path_check_thread = QThread()
        self._remote_path_check_worker = PathCheckWorker(remote_project_path)
        self._remote_path_check_worker.moveToThread(self._remote_path_check_thread)

        self._remote_path_check_thread.started.connect(self._remote_path_check_worker.run)
        self._remote_path_check_worker.finished.connect(self._on_remote_path_check_finished)
        self._remote_path_check_worker.finished.connect(self._remote_path_check_thread.quit)
        self._remote_path_check_worker.finished.connect(self._remote_path_check_worker.deleteLater)
        self._remote_path_check_thread.finished.connect(self._remote_path_check_thread.deleteLater)
        self._remote_path_check_thread.finished.connect(self._clear_remote_path_check_thread)

        self._remote_path_check_thread.start()

    def _on_remote_path_check_finished(self, accessible, path_checked):
        """Called when the background remote address accessibility check completes."""
        if self.refreshMountButton:
            self.refreshMountButton.setEnabled(True)
        if accessible:
            self.log_to_console(
                f"✔  Remote project path accessible: {path_checked}",
                ui_utils.COLOR_SUCCESS
            )
            if self.loginButton:
                self.loginButton.setEnabled(True)
        else:
            self.log_to_console(
                f"✖  Remote project path NOT accessible: {path_checked}",
                ui_utils.COLOR_ERROR
            )
            if self.loginButton:
                self.loginButton.setEnabled(False)

    def _on_remote_address_text_changed(self, text):
        """Disables the login button while the user is typing. Validation runs on Enter or Refresh."""
        if self.loginButton:
            self.loginButton.setEnabled(False)

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

        # local_address  = DB mountpoint = locally mapped drive (e.g. Z:\Projects)
        #                  validated to be accessible before reaching this point
        local_address = (self.project_data.get("data") or {}).get("mountpoint", "") if self.project_data else ""

        # remote_address = studio server VPN UNC path (e.g. \\\\10.0.0.100\\storage\\Projects)
        #                  source of truth for context scanning
        remote_address = self.remoteAddressLineEdit.text().strip() if self.remoteAddressLineEdit else ""

        # Save last project
        self.config_service.save_last_project(self.project_data.get("id"))

        project_id = self.project_data.get("id", "")
        if project_id:
            if local_address:
                self.config_service.save_local_mount_point(project_id, local_address)
            if remote_address:
                self.config_service.save_remote_address(project_id, remote_address)

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
            remote_address=remote_address,
            local_address=local_address,
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
