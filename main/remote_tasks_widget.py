import os
import traceback
from pathlib import Path

from PySide6 import QtWidgets, QtCore
from PySide6.QtCore import Qt, QObject, Signal, QThread, QThreadPool, QRunnable
from PySide6.QtGui import QStandardItemModel, QStandardItem, QBrush, QColor, QFont, QPixmap

from services import gazu_api, ui_utils
from .publisher_dialog import PublisherDialog


class PublishWorker(QObject):
    """Background worker for publishing to Kitsu."""
    finished = Signal(bool, object)

    def __init__(self, task, task_status, comment, file_path):
        super().__init__()
        self.task = task
        self.task_status = task_status
        self.comment = comment
        self.file_path = file_path

    def run(self):
        try:
            success, result = gazu_api.publish_preview_to_task(
                task=self.task,
                task_status=self.task_status,
                comment=self.comment,
                file_path=self.file_path,
            )
            self.finished.emit(success, result)
        except Exception as e:
            traceback.print_exc()
            self.finished.emit(False, str(e))


class ThumbnailSignals(QObject):
    finished = Signal(bool, str)


class ThumbnailRunnable(QRunnable):
    """Downloads a preview thumbnail in a thread pool."""
    def __init__(self, preview_file_id, thumbnail_path, signals):
        super().__init__()
        self.preview_file_id = preview_file_id
        self.thumbnail_path = thumbnail_path
        self.signals = signals
        self.setAutoDelete(True)

    def run(self):
        try:
            success, _ = gazu_api.download_preview_file_thumbnail(
                self.preview_file_id, self.thumbnail_path
            )
            self.signals.finished.emit(success, self.preview_file_id)
        except Exception:
            self.signals.finished.emit(False, self.preview_file_id)


class RemoteTasksWidget(QtWidgets.QWidget):
    """
    Displays the logged-in user's tasks for the current project.
    Provides task feedback (status + comment) and publish functionality.
    No DCC launcher, no filesystem browsing, no scaffold.
    """

    task_selection_changed = Signal(dict)

    def __init__(self, tasks_tree_view, thumbnail_label, project_data, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.debug_mode = getattr(parent, "debug_mode", False)

        self.tasks_tree_view = tasks_tree_view
        self.thumbnail_label = thumbnail_label
        self.project_data = project_data
        self.hierarchy_cache = {}

        # Thumbnail download pool (max 1 concurrent)
        self.active_thumbnail_downloads = set()
        self.thumbnail_item_mapping = {}
        self.thumbnail_thread_pool = QThreadPool(self)
        self.thumbnail_thread_pool.setMaxThreadCount(2)
        self.thumbnail_signals = ThumbnailSignals()
        self.thumbnail_signals.finished.connect(self._on_thumbnail_download_finished)

        # Publisher tracking (prevent garbage collection)
        if not hasattr(self.main_window, "active_publishers"):
            self.main_window.active_publishers = []

        self._setup_task_view()

    # -------------------------------------------------------------------------
    # Setup
    # -------------------------------------------------------------------------

    def _setup_task_view(self):
        """Initializes the task tree view and its model."""
        self.task_model = QStandardItemModel(self)
        self.task_model.setHorizontalHeaderLabels(["Name", "Type", "Status"])
        self.tasks_tree_view.setModel(self.task_model)
        self.tasks_tree_view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tasks_tree_view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.tasks_tree_view.setIconSize(QtCore.QSize(39, 26))
        self.tasks_tree_view.setContextMenuPolicy(Qt.CustomContextMenu)

        # Uniform row height
        stylesheet = "QTreeView::item { height: 26px; }"
        self.tasks_tree_view.setStyleSheet(stylesheet)

        # Signals
        self.tasks_tree_view.selectionModel().selectionChanged.connect(self.on_task_selection_changed)
        self.tasks_tree_view.customContextMenuRequested.connect(self.on_task_context_menu)
        self.tasks_tree_view.doubleClicked.connect(self._on_task_double_clicked)

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def _log(self, message, color=ui_utils.COLOR_INFO):
        """Forwards log calls to the main window."""
        if self.main_window and hasattr(self.main_window, "log_to_console"):
            self.main_window.log_to_console(message, color)
        else:
            print(f"[{color}] {message}")

    # -------------------------------------------------------------------------
    # Populate task tree
    # -------------------------------------------------------------------------

    def populate_task_view(self, tasks):
        """
        Fills the task tree with tasks grouped by hierarchy:
        TV Show: Episode → Sequence → Shot → Task
        Film:    Sequence → Shot → Task
        Asset:   Asset Type → Asset → Task
        Tasks come directly from the API (no path resolution).
        """
        self.task_model.clear()
        self.thumbnail_item_mapping.clear()
        self.active_thumbnail_downloads.clear()
        self.hierarchy_cache = {}

        self.task_model.setHorizontalHeaderLabels(["Name", "Type", "Status"])
        root = self.task_model.invisibleRootItem()
        project_type = self.project_data.get("production_type", "").lower()

        for task in tasks:
            entity_type = task.get("task_type_for_entity")
            hierarchy_path = []

            if entity_type == "Shot":
                episode_name = task.get("episode_name")
                sequence_name = task.get("sequence_name")
                entity_name = task.get("entity_name")

                if project_type == "tvshow" and episode_name:
                    hierarchy_path.append(("Episode", episode_name))
                if sequence_name:
                    hierarchy_path.append(("Sequence", sequence_name))
                if entity_name:
                    hierarchy_path.append(("Shot", entity_name))

            elif entity_type == "Asset":
                asset_type_name = task.get("entity_type_name", "")
                entity_name = task.get("entity_name")
                if asset_type_name:
                    hierarchy_path.append(("Asset Type", asset_type_name))
                if entity_name:
                    hierarchy_path.append(("Asset", entity_name))

            parent_item = self._get_or_create_parent(root, hierarchy_path)

            # --- Build task row ---
            task_type_name = task.get("task_type_name", "N/A")
            task_status = task.get("task_status_name", "N/A")
            task_color = task.get("task_status_color", "")

            task_item = QStandardItem(task_type_name)
            task_item.setEditable(False)
            task_item.setData(task, Qt.UserRole + 2)

            type_item = QStandardItem("Task")
            type_item.setEditable(False)

            status_item = QStandardItem(task_status)
            status_item.setEditable(False)
            if task_color:
                status_item.setForeground(QBrush(QColor(task_color)))

            parent_item.appendRow([task_item, type_item, status_item])

            # Queue thumbnail download
            preview_file_id = task.get("entity_preview_file_id")
            if preview_file_id and preview_file_id not in self.active_thumbnail_downloads:
                thumbnail_path = ui_utils.get_thumbnail_path(preview_file_id)
                if thumbnail_path and not thumbnail_path.exists():
                    self.active_thumbnail_downloads.add(preview_file_id)
                    if task_item not in self.thumbnail_item_mapping.get(preview_file_id, []):
                        self.thumbnail_item_mapping.setdefault(preview_file_id, []).append(task_item)
                    runnable = ThumbnailRunnable(
                        preview_file_id, str(thumbnail_path), self.thumbnail_signals
                    )
                    self.thumbnail_thread_pool.start(runnable)
                elif thumbnail_path and thumbnail_path.exists():
                    self.thumbnail_item_mapping.setdefault(preview_file_id, []).append(task_item)

        # Sort and expand
        self._sort_tree(root)
        self.tasks_tree_view.expandAll()
        self.tasks_tree_view.resizeColumnToContents(0)

    def _get_or_create_parent(self, root, hierarchy_path):
        """Returns (or creates) the correct parent tree item for a given hierarchy path."""
        current = root
        cache_key = ()

        for level_type, level_name in hierarchy_path:
            cache_key = cache_key + (level_type, level_name)
            if cache_key in self.hierarchy_cache:
                current = self.hierarchy_cache[cache_key]
            else:
                new_item = QStandardItem(level_name)
                new_item.setEditable(False)
                font = QFont()
                font.setBold(True)
                new_item.setFont(font)
                new_item.setData(level_type, Qt.UserRole + 3)

                placeholder_type = QStandardItem(level_type)
                placeholder_type.setEditable(False)
                placeholder_status = QStandardItem("")
                placeholder_status.setEditable(False)

                current.appendRow([new_item, placeholder_type, placeholder_status])
                self.hierarchy_cache[cache_key] = new_item
                current = new_item

        return current

    def _sort_tree(self, parent):
        """Recursively sorts tree items alphabetically."""
        parent.sortChildren(0, Qt.AscendingOrder)
        for row in range(parent.rowCount()):
            child = parent.child(row, 0)
            if child and child.hasChildren():
                self._sort_tree(child)

    # -------------------------------------------------------------------------
    # Thumbnail
    # -------------------------------------------------------------------------

    def _on_thumbnail_download_finished(self, success, preview_file_id):
        """Called when a thumbnail download completes."""
        self.active_thumbnail_downloads.discard(preview_file_id)
        if success:
            # Update any tree items linked to this thumbnail
            items = self.thumbnail_item_mapping.get(preview_file_id, [])
            for item in items:
                if item.model():
                    # Trigger a data change so views can re-render (icon update done in selection)
                    item.setData(item.data(Qt.UserRole + 2), Qt.UserRole + 2)

    def _show_thumbnail(self, task_data):
        """Displays the cached thumbnail for the selected task."""
        if not self.thumbnail_label:
            return
        if not task_data:
            self.thumbnail_label.clear()
            return

        preview_file_id = task_data.get("entity_preview_file_id")
        entity_type = task_data.get("task_type_for_entity")

        if entity_type not in ("Shot", "Asset") or not preview_file_id:
            self.thumbnail_label.clear()
            return

        thumbnail_path = ui_utils.get_thumbnail_path(preview_file_id)
        if thumbnail_path and thumbnail_path.exists():
            pixmap = QPixmap(str(thumbnail_path))
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.thumbnail_label.size(),
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation,
                )
                self.thumbnail_label.setPixmap(scaled)
                return

        self.thumbnail_label.clear()

    # -------------------------------------------------------------------------
    # Selection
    # -------------------------------------------------------------------------

    def on_task_selection_changed(self, selected, deselected):
        """Handles task tree selection changes."""
        indexes = selected.indexes()
        if not indexes:
            self.task_selection_changed.emit({})
            return

        item = self.task_model.itemFromIndex(indexes[0])
        if not item:
            return

        task_data = item.data(Qt.UserRole + 2)
        if not isinstance(task_data, dict):
            # Parent node selected – clear the detail panel
            self.task_selection_changed.emit({})
            self._show_thumbnail(None)
            return

        self.task_selection_changed.emit(task_data)
        self._show_thumbnail(task_data)

    def _get_selected_task(self):
        """Returns the task dict for the currently selected task row, or None."""
        indexes = self.tasks_tree_view.selectedIndexes()
        if not indexes:
            return None
        item = self.task_model.itemFromIndex(indexes[0])
        if not item:
            return None
        data = item.data(Qt.UserRole + 2)
        return data if isinstance(data, dict) else None

    # -------------------------------------------------------------------------
    # Double-click → open Kitsu in browser
    # -------------------------------------------------------------------------

    def _on_task_double_clicked(self, index):
        """Opens the Kitsu task page in the default browser on double-click."""
        item = self.task_model.itemFromIndex(index)
        if not item:
            return
        task_data = item.data(Qt.UserRole + 2)
        if not isinstance(task_data, dict):
            return

        if hasattr(self.main_window, "kitsu_base_url") and self.main_window.kitsu_base_url:
            project_id = self.project_data.get("id", "")
            url = ui_utils.get_kitsu_task_url(
                self.main_window.kitsu_base_url, project_id, task_data
            )
            if url:
                import webbrowser
                webbrowser.open(url)

    # -------------------------------------------------------------------------
    # Context menu
    # -------------------------------------------------------------------------

    def on_task_context_menu(self, pos):
        """Shows a context menu for the selected task."""
        task_data = self._get_selected_task()
        if not task_data:
            return

        menu = QtWidgets.QMenu(self)

        action_publish = menu.addAction("Publish to Kitsu...")
        action_comment = menu.addAction("Add Comment / Feedback...")
        menu.addSeparator()
        action_open_web = menu.addAction("Open in Kitsu (Browser)")

        action = menu.exec(self.tasks_tree_view.viewport().mapToGlobal(pos))

        if action == action_publish:
            self.publish_to_kitsu(task_data)
        elif action == action_comment:
            self.add_comment_to_task(task_data)
        elif action == action_open_web:
            self._on_task_double_clicked(self.tasks_tree_view.selectedIndexes()[0])

    # -------------------------------------------------------------------------
    # Publish
    # -------------------------------------------------------------------------

    def publish_to_kitsu(self, task_data=None):
        """
        Opens the PublisherDialog and, on accept, publishes the preview
        to Kitsu on a background thread.
        """
        if task_data is None:
            task_data = self._get_selected_task()
        if not task_data:
            self._log("No task selected.", ui_utils.COLOR_WARNING)
            return

        # Fetch fresh task data from API (SSOT)
        task_id = task_data.get("id")
        if task_id:
            success, fresh = gazu_api.get_task(task_id)
            if success and fresh:
                task_data = self._merge_task_data(task_data, fresh)

        # Fetch task statuses
        status_ok, all_statuses = gazu_api.get_task_statuses()
        if not status_ok or not all_statuses:
            self._log("Failed to fetch task statuses.", ui_utils.COLOR_ERROR)
            return

        dlg = PublisherDialog(task_data, all_statuses, parent=self.main_window)
        result = dlg.exec()

        if result != QtWidgets.QDialog.Accepted:
            return

        file_path = dlg.get_file_path()
        if not file_path or not os.path.isfile(file_path):
            self._log("Publish cancelled: no valid file selected.", ui_utils.COLOR_WARNING)
            return

        selected_status = dlg.get_selected_status()
        comment = dlg.get_comment()
        file_name = os.path.basename(file_path)

        self._log(f"Publishing '{file_name}' → {selected_status.get('name', '?')}...", ui_utils.COLOR_INFO)

        # Background publish
        thread = QThread()
        worker = PublishWorker(task_data, selected_status, comment, file_path)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(lambda ok, res: self._on_publish_finished(ok, res, file_name))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda: self.main_window.active_publishers.remove((thread, worker))
            if (thread, worker) in self.main_window.active_publishers else None
        )

        self.main_window.active_publishers.append((thread, worker))
        thread.start()

    def _on_publish_finished(self, success, result, file_name):
        """Handles the publish worker result."""
        if success:
            self._log(f"Published '{file_name}' successfully.", ui_utils.COLOR_SUCCESS)
        else:
            self._log(f"Publish failed for '{file_name}': {result}", ui_utils.COLOR_ERROR)

    # -------------------------------------------------------------------------
    # Comment / feedback (no file)
    # -------------------------------------------------------------------------

    def add_comment_to_task(self, task_data=None):
        """
        Opens a simple dialog to add a comment and status update to a task
        without attaching a file.
        """
        if task_data is None:
            task_data = self._get_selected_task()
        if not task_data:
            self._log("No task selected.", ui_utils.COLOR_WARNING)
            return

        # Fetch fresh task data
        task_id = task_data.get("id")
        if task_id:
            success, fresh = gazu_api.get_task(task_id)
            if success and fresh:
                task_data = self._merge_task_data(task_data, fresh)

        status_ok, all_statuses = gazu_api.get_task_statuses()
        if not status_ok:
            self._log("Failed to fetch task statuses.", ui_utils.COLOR_ERROR)
            return

        dlg = _CommentDialog(task_data, all_statuses, parent=self.main_window)
        result = dlg.exec()

        if result != QtWidgets.QDialog.Accepted:
            return

        selected_status = dlg.get_selected_status()
        comment = dlg.get_comment()

        if not comment.strip():
            self._log("Comment is empty – nothing sent.", ui_utils.COLOR_WARNING)
            return

        self._log("Sending comment...", ui_utils.COLOR_INFO)
        ok, res = gazu_api.add_comment_to_task(task_data, selected_status, comment)
        if ok:
            self._log("Comment added successfully.", ui_utils.COLOR_SUCCESS)
        else:
            self._log(f"Failed to add comment: {res}", ui_utils.COLOR_ERROR)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _merge_task_data(base, fresh):
        """Merges fresh API task data into the base task data dict."""
        merged = dict(base)
        # Refresh status
        if "task_status_id" in fresh:
            merged["task_status_id"] = fresh["task_status_id"]
        # Refresh entity info
        entity = fresh.get("entity", {})
        if isinstance(entity, dict):
            if "name" in entity:
                merged["entity_name"] = entity["name"]
        task_type = fresh.get("task_type", {})
        if isinstance(task_type, dict):
            if "name" in task_type:
                merged["task_type_name"] = task_type["name"]
            if "for_entity" in task_type:
                merged["task_type_for_entity"] = task_type["for_entity"]
        for key in ("sequence_name", "episode_name", "project_name"):
            if key in fresh:
                merged[key] = fresh[key]
        return merged

    def cleanup(self):
        """Disconnects signals before the widget is destroyed."""
        try:
            self.tasks_tree_view.selectionModel().selectionChanged.disconnect(
                self.on_task_selection_changed
            )
        except (TypeError, RuntimeError):
            pass
        try:
            self.tasks_tree_view.customContextMenuRequested.disconnect(self.on_task_context_menu)
        except (TypeError, RuntimeError):
            pass
        self.thumbnail_thread_pool.clear()


# ---------------------------------------------------------------------------
# Lightweight comment-only dialog
# ---------------------------------------------------------------------------

class _CommentDialog(QtWidgets.QDialog):
    """
    A simplified dialog for adding a comment + status change to a task
    without attaching a file.
    """

    def __init__(self, task_data, all_statuses, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Comment / Feedback")
        self.setMinimumWidth(420)

        layout = QtWidgets.QVBoxLayout(self)

        # Task info
        info_group = QtWidgets.QGroupBox("Task")
        form = QtWidgets.QFormLayout()
        for label, key in [
            ("Project", "project_name"),
            ("Episode", "episode_name"),
            ("Sequence", "sequence_name"),
            ("Entity", "entity_name"),
            ("Task", "task_type_name"),
        ]:
            value = task_data.get(key, "")
            if value and value != "N/A":
                form.addRow(f"<b>{label}:</b>", QtWidgets.QLabel(value))
        info_group.setLayout(form)
        layout.addWidget(info_group)

        # Status combo
        status_group = QtWidgets.QGroupBox("Status")
        status_vbox = QtWidgets.QVBoxLayout()
        self.status_combo = QtWidgets.QComboBox()
        current_status_id = task_data.get("task_status_id")
        for status in all_statuses:
            self.status_combo.addItem(status["name"], status)
            if status["id"] == current_status_id:
                self.status_combo.setCurrentIndex(self.status_combo.count() - 1)
        status_vbox.addWidget(self.status_combo)
        status_group.setLayout(status_vbox)
        layout.addWidget(status_group)

        # Comment
        comment_group = QtWidgets.QGroupBox("Comment")
        comment_vbox = QtWidgets.QVBoxLayout()
        self.comment_edit = QtWidgets.QTextEdit()
        self.comment_edit.setPlaceholderText("Enter your feedback here...")
        self.comment_edit.setMinimumHeight(80)
        comment_vbox.addWidget(self.comment_edit)
        comment_group.setLayout(comment_vbox)
        layout.addWidget(comment_group)

        # Buttons
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        ok_btn = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        if ok_btn:
            ok_btn.setText("Send")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_selected_status(self):
        return self.status_combo.currentData()

    def get_comment(self):
        return ui_utils.format_comment_html(self.comment_edit.toPlainText())
