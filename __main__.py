import sys
import os
import ctypes
from PySide6 import QtWidgets, QtGui

# Ensure project root is in sys.path so 'services', 'login', 'main' are importable
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from login.login_view import RemoteLoginView

if __name__ == "__main__":
    # Tell Windows this is a standalone app (correct taskbar icon)
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GazuRemote.App.1")

    app = QtWidgets.QApplication(sys.argv)

    # Application-level icon
    _icon_path = os.path.join(project_root, "images", "gazu_remote.ico")
    if os.path.exists(_icon_path):
        app.setWindowIcon(QtGui.QIcon(_icon_path))

    login_window = RemoteLoginView()
    login_window.display()

    sys.exit(app.exec())
