import datetime
import json
import os
import traceback
import webbrowser
from pathlib import Path

from PySide6 import QtWidgets, QtCore
from PySide6.QtCore import Qt, QObject, Signal, QThread, QThreadPool, QRunnable, QMimeData
from PySide6.QtGui import (
    QStandardItemModel, QStandardItem, QBrush, QColor, QFont, QPixmap, QIcon
)
from PySide6.QtWidgets import QFileIconProvider

from services import gazu_api, ui_utils
from .publisher_dialog import PublisherDialog


# ---------------------------------------------------------------------------
# Colors for path-availability feedback
# ---------------------------------------------------------------------------
COLOR_NO_PATH   = QColor(150, 50, 50)   # red – task/parent with unsynced files
COLOR_PARENT_OK = QColor(50, 150, 50)  # green – all tasks found under this parent


# ---------------------------------------------------------------------------
# Background worker: scan remote_address/project_name for .gazu_context files
# ---------------------------------------------------------------------------

class ContextScanWorker(QObject):
    """
    Recursively walks ``root_path`` and collects all ``.gazu_context`` files.
    Builds a mapping  ``{task_id: folder_path}``  and emits it on finish.
    """
    finished = Signal(dict)   # {task_id: folder_path_str}
    progress = Signal(str)    # optional status messages

    def __init__(self, root_path: str):
        super().__init__()
        self._root = root_path
        self._cancelled = False

    def cancel(self):
        """Request early termination. Safe to call from any thread."""
        self._cancelled = True

    def run(self):
        result: dict = {}
        try:
            for dirpath, dirnames, filenames in os.walk(self._root):
                if self._cancelled:
                    break
                # Skip hidden dirs to stay fast on large trees
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                if ".gazu_context" in filenames:
                    ctx_path = os.path.join(dirpath, ".gazu_context")
                    try:
                        with open(ctx_path, "r", encoding="utf-8") as fh:
                            data = json.load(fh)
                        # Support both 'task_id' (written by Gazu) and 'id' variants
                        tid = data.get("task_id") or data.get("id")
                        if tid:
                            result[tid] = dirpath
                    except Exception:
                        pass   # corrupt file – skip silently
        except Exception as e:
            self.progress.emit(f"Context scan error: {e}")
        self.finished.emit(result)


# ---------------------------------------------------------------------------
# Read-only filesystem model (drag = copy only)
# ---------------------------------------------------------------------------

class ReadOnlyFileSystemModel(QtWidgets.QFileSystemModel):
    def supportedDragActions(self):
        return Qt.CopyAction


# ---------------------------------------------------------------------------
# Proxy that can hide all content (used to keep the dir tree blank when no
# task is selected, while the underlying model is already set to a root).
# ---------------------------------------------------------------------------

class EmptyRootProxyModel(QtCore.QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._show = False
        self._header_title = None

    def setShowContent(self, show: bool):
        self._show = show
        self.invalidateFilter()

    def setHeaderTitle(self, title):
        """Sets a custom title for the first column's header."""
        self._header_title = title
        self.headerDataChanged.emit(Qt.Horizontal, 0, 0)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if self._header_title and orientation == Qt.Horizontal and section == 0 and role == Qt.DisplayRole:
            return self._header_title
        return super().headerData(section, orientation, role)

    def filterAcceptsRow(self, source_row, source_parent):
        if not self._show:
            return False
        return super().filterAcceptsRow(source_row, source_parent)


# ---------------------------------------------------------------------------
# Files table model (drag = copy, exposes local file URLs)
# ---------------------------------------------------------------------------

class FileTableModel(QStandardItemModel):
    HEADERS = ["Workfiles", "Size", "Modified"]

    def __init__(self, parent=None):
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels(self.HEADERS)

    def mimeData(self, indexes):
        paths = set()
        for idx in indexes:
            if idx.column() == 0:
                item = self.item(idx.row(), 0)
                if item:
                    p = item.data(Qt.UserRole + 1)
                    if p:
                        paths.add(p)
        if not paths:
            return QMimeData()
        mime = QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile(p) for p in paths])
        return mime

    def supportedDragActions(self):
        return Qt.CopyAction

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.TextAlignmentRole:
            return Qt.AlignLeft | Qt.AlignVCenter
        return super().headerData(section, orientation, role)


# ---------------------------------------------------------------------------
# Background workers for publish and thumbnail
# ---------------------------------------------------------------------------

class PublishWorker(QObject):
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


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class RemoteTasksWidget(QtWidgets.QWidget):
    """
    Three-panel task view for GazuRemote:
      1. Task tree  – grouped hierarchy, tasks colored orange if local folder
                      not found (no .gazu_context match)
      2. Directories tree  – local filesystem tree rooted at the task folder
      3. Files table  – flat list of files in the selected directory

    Path resolution: two background scans run in parallel:
      - ``remote_address`` (UNC/VPN path, e.g. ``\\\\server\\storage\\Projects``) – source of truth
      - ``local_address``  (mapped drive, e.g. ``Z:\\Projects``) – synced local copy
    Tasks are colored orange when missing from the local drive; the file-browser
    panels always prefer the local path for speed.
    """

    task_selection_changed = Signal(dict)

    def __init__(
        self,
        tasks_tree_view,
        thumbnail_label,
        project_data,
        directories_tree_view=None,
        files_table_view=None,
        remote_address="",
        local_address="",
        parent=None,
    ):
        super().__init__(parent)
        self.main_window = parent
        self.debug_mode = getattr(parent, "debug_mode", False)

        self.tasks_tree_view = tasks_tree_view
        self.thumbnail_label = thumbnail_label
        self.directories_tree_view = directories_tree_view
        self.files_table_view = files_table_view
        self.project_data = project_data
        self.remote_address = remote_address
        self.local_address = local_address
        self.hierarchy_cache = {}

        # task_id -> folder_path, populated by ContextScanWorker for each root
        self._remote_task_path_map: dict = {}
        self._local_task_path_map: dict = {}
        self._remote_scan_thread = None
        self._local_scan_thread = None
        # Keep strong references to workers – without this Python GC kills them
        # before the background thread finishes (QThread holds no Python ref).
        self._remote_scan_worker = None
        self._local_scan_worker = None
        # Incremented on every restart; finished callbacks ignore stale generations.
        self._scan_generation: int = 0

        # Thumbnail pool
        self.active_thumbnail_downloads: set = set()
        self.thumbnail_item_mapping: dict = {}
        self.thumbnail_thread_pool = QThreadPool(self)
        self.thumbnail_thread_pool.setMaxThreadCount(1)
        self.thumbnail_signals = ThumbnailSignals()
        self.thumbnail_signals.finished.connect(self._on_thumbnail_download_finished)

        # Publisher tracking
        if not hasattr(self.main_window, "active_publishers"):
            self.main_window.active_publishers = []

        # Icon provider for file icons
        self.icon_provider = QFileIconProvider()

        self._apply_uniform_styles()
        self._setup_task_view()
        self._setup_dir_and_file_views()
        self._start_context_scan()

    # -------------------------------------------------------------------------
    # Setup
    # -------------------------------------------------------------------------

    def _apply_uniform_styles(self):
        """Applies a consistent stylesheet to all views for a uniform look and feel."""
        uniform_row_height = 26
        stylesheet = f"""
            QTreeView::item {{
                height: {uniform_row_height}px;
            }}
        """
        self.tasks_tree_view.setStyleSheet(stylesheet)
        if self.directories_tree_view:
            self.directories_tree_view.setStyleSheet(stylesheet)
        # files_table_view row height is controlled via verticalHeader().setDefaultSectionSize()

    def _setup_task_view(self):
        self.task_model = QStandardItemModel(self)
        self.task_model.setHorizontalHeaderLabels(["Name", "Type", "Status"])
        self.tasks_tree_view.setModel(self.task_model)
        self.tasks_tree_view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tasks_tree_view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.tasks_tree_view.setIconSize(QtCore.QSize(39, 26))
        self.tasks_tree_view.setContextMenuPolicy(Qt.CustomContextMenu)

        sel_model = self.tasks_tree_view.selectionModel()
        sel_model.selectionChanged.connect(self.on_task_selection_changed)
        self.tasks_tree_view.customContextMenuRequested.connect(self.on_task_context_menu)
        self.tasks_tree_view.doubleClicked.connect(self._on_task_double_clicked)

    def _setup_dir_and_file_views(self):
        # ── Directories tree ──────────────────────────────────────────────
        if self.directories_tree_view:
            self.dir_model = ReadOnlyFileSystemModel(self)
            self.dir_model.setFilter(
                QtCore.QDir.NoDotAndDotDot | QtCore.QDir.AllDirs
            )
            self.dir_model.setRootPath("")

            self.dir_proxy = EmptyRootProxyModel(self)
            self.dir_proxy.setSourceModel(self.dir_model)
            self.dir_proxy.setHeaderTitle("Directories")

            self.directories_tree_view.setModel(self.dir_proxy)
            self.directories_tree_view.setEditTriggers(
                QtWidgets.QAbstractItemView.NoEditTriggers
            )
            self.directories_tree_view.setDragEnabled(True)
            self.directories_tree_view.setDragDropMode(
                QtWidgets.QAbstractItemView.DragOnly
            )
            # Hide size / type / date columns – show only name
            for col in range(1, 4):
                self.directories_tree_view.hideColumn(col)
            self.directories_tree_view.sortByColumn(0, Qt.DescendingOrder)
            self.directories_tree_view.selectionModel().selectionChanged.connect(
                self.on_directory_selection_changed
            )
            self.directories_tree_view.setContextMenuPolicy(Qt.CustomContextMenu)
            self.directories_tree_view.customContextMenuRequested.connect(
                self._on_dir_context_menu
            )
            self.directories_tree_view.doubleClicked.connect(self._on_dir_double_clicked)

        # ── Files table ───────────────────────────────────────────────────
        if self.files_table_view:
            self.files_model = FileTableModel(self)
            self.files_table_view.setModel(self.files_model)
            self.files_table_view.setEditTriggers(
                QtWidgets.QAbstractItemView.NoEditTriggers
            )
            self.files_table_view.setSelectionBehavior(
                QtWidgets.QAbstractItemView.SelectRows
            )
            self.files_table_view.setSelectionMode(
                QtWidgets.QAbstractItemView.SingleSelection
            )
            self.files_table_view.setSortingEnabled(True)
            self.files_table_view.verticalHeader().hide()
            self.files_table_view.verticalHeader().setDefaultSectionSize(26)
            self.files_table_view.setDragEnabled(True)
            self.files_table_view.setDragDropMode(
                QtWidgets.QAbstractItemView.DragOnly
            )
            self.files_table_view.horizontalHeader().setStretchLastSection(False)
            self.files_table_view.horizontalHeader().setSectionResizeMode(
                0, QtWidgets.QHeaderView.Stretch
            )
            self.files_table_view.sortByColumn(0, Qt.DescendingOrder)
            self.files_table_view.setContextMenuPolicy(Qt.CustomContextMenu)
            self.files_table_view.customContextMenuRequested.connect(
                self._on_file_context_menu
            )
            self.files_table_view.doubleClicked.connect(self._on_file_double_clicked)

    # -------------------------------------------------------------------------
    # Context scan (background)
    # -------------------------------------------------------------------------

    def restart_context_scan(self):
        """Clears existing scan results and re-runs both remote and local scans.
        Increments _scan_generation so any still-running old thread's finished
        signal is silently ignored when it eventually arrives.
        """
        # Signal cancellation to workers still in their os.walk loop.
        for worker in (self._remote_scan_worker, self._local_scan_worker):
            if worker is not None:
                worker.cancel()
        # Bump generation BEFORE nulling refs – the old threads may call
        # _clear_* after this, but the generation guard will be in effect.
        self._scan_generation += 1
        self._remote_task_path_map = {}
        self._local_task_path_map = {}
        self._remote_scan_thread = None
        self._local_scan_thread = None
        self._remote_scan_worker = None
        self._local_scan_worker = None
        self._start_context_scan()

    def _start_context_scan(self):
        """Start background .gazu_context scans for remote and (optionally) local roots."""
        project_name = self.project_data.get("name", "") if self.project_data else ""
        if not project_name:
            return
        if self.remote_address:
            remote_root = os.path.join(self.remote_address, project_name)
            self._log(f"Remote root resolved: {remote_root}  exists={os.path.isdir(remote_root)}", ui_utils.COLOR_INFO)
            self._launch_scan(remote_root, is_local=False)
        if self.local_address:
            local_root = os.path.join(self.local_address, project_name)
            self._log(f"Local root resolved:  {local_root}  exists={os.path.isdir(local_root)}", ui_utils.COLOR_INFO)
            self._launch_scan(local_root, is_local=True)

    def _launch_scan(self, scan_root: str, is_local: bool):
        label = "local" if is_local else "remote"
        if not os.path.isdir(scan_root):
            self._log(f"Project folder not found ({label}): {scan_root}", ui_utils.COLOR_WARNING)
            return

        self._log(f"Scanning {label} task folders: {scan_root}", ui_utils.COLOR_INFO)

        worker = ContextScanWorker(scan_root)
        thread = QThread()
        worker.moveToThread(thread)

        # Capture generation at launch time; callbacks discard results from
        # old scans that were cancelled but finished after a restart.
        captured_gen = self._scan_generation
        finished_slot = self._on_local_scan_finished if is_local else self._on_remote_scan_finished
        clear_slot = self._clear_local_scan_thread if is_local else self._clear_remote_scan_thread

        def _guarded_finished(path_map: dict):
            if self._scan_generation == captured_gen:
                finished_slot(path_map)

        def _guarded_clear():
            if self._scan_generation == captured_gen:
                clear_slot()

        thread.started.connect(worker.run)
        worker.progress.connect(lambda msg: self._log(msg, ui_utils.COLOR_WARNING))
        worker.finished.connect(_guarded_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(_guarded_clear)

        if is_local:
            self._local_scan_thread = thread
            self._local_scan_worker = worker   # prevent GC
        else:
            self._remote_scan_thread = thread
            self._remote_scan_worker = worker  # prevent GC
        thread.start()

    def _clear_remote_scan_thread(self):
        self._remote_scan_thread = None
        self._remote_scan_worker = None

    def _clear_local_scan_thread(self):
        self._local_scan_thread = None
        self._local_scan_worker = None

    def _on_remote_scan_finished(self, path_map: dict):
        self._remote_task_path_map = path_map
        self._log(f"Remote scan complete – {len(path_map)} task folder(s) found.", ui_utils.COLOR_SUCCESS)
        if self.debug_mode:
            for tid, fpath in path_map.items():
                self._log(f"  [remote] {tid}  →  {fpath}", ui_utils.COLOR_INFO)
        self._apply_path_coloring(source="remote_scan")

    def _on_local_scan_finished(self, path_map: dict):
        self._local_task_path_map = path_map
        self._log(f"Local scan complete – {len(path_map)} task folder(s) synced.", ui_utils.COLOR_SUCCESS)
        if self.debug_mode:
            for tid, fpath in path_map.items():
                self._log(f"  [local]  {tid}  →  {fpath}", ui_utils.COLOR_INFO)
        self._apply_path_coloring(source="local_scan")

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def _log(self, message, color=ui_utils.COLOR_INFO):
        if self.main_window and hasattr(self.main_window, "log_to_console"):
            self.main_window.log_to_console(message, color)
        else:
            print(f"[{color}] {message}")

    # -------------------------------------------------------------------------
    # Populate task tree
    # -------------------------------------------------------------------------

    def populate_task_view(self, tasks):
        """
        Fills the task tree.  Tasks whose task_id is NOT in the local path map
        are shown with an orange foreground (local folder missing/not synced yet).
        """
        self.task_model.clear()
        self.thumbnail_item_mapping.clear()
        self.active_thumbnail_downloads.clear()
        self.hierarchy_cache = {}

        self.task_model.setHorizontalHeaderLabels(["Name", "Type", "Status"])
        root = self.task_model.invisibleRootItem()
        project_type = self.project_data.get("production_type", "").lower()

        # Track which entity parent items already received a thumbnail (one per entity)
        _entity_thumbnail_assigned: set = set()

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

            task_type_name = task.get("task_type_name", "N/A")
            task_status = task.get("task_status_name", "N/A")
            task_color = task.get("task_status_color", "")
            task_id = task.get("id", "")

            task_item = QStandardItem(task_type_name)
            task_item.setEditable(False)
            task_item.setData(task, Qt.UserRole + 2)

            task_item.setData(self._resolve_task_path(task_id), Qt.UserRole + 1)

            type_item = QStandardItem("Task")
            type_item.setEditable(False)

            status_item = QStandardItem(task_status)
            status_item.setEditable(False)
            if task_color:
                status_item.setForeground(QBrush(QColor(task_color)))

            parent_item.appendRow([task_item, type_item, status_item])

            # Thumbnail on the entity parent item (Shot / Asset) – once per entity only
            preview_file_id = task.get("entity_preview_file_id")
            entity_id = task.get("entity_id", "")
            if preview_file_id and entity_id not in _entity_thumbnail_assigned:
                _entity_thumbnail_assigned.add(entity_id)
                self._handle_thumbnail_caching_for_item(preview_file_id, parent_item)

        self._sort_tree(root)
        self.tasks_tree_view.expandAll()
        self.tasks_tree_view.resizeColumnToContents(0)
        # Only color if at least one scan has already finished; otherwise leave
        # items in default (white) color and let the scan-finished slot color them.
        if self._local_task_path_map or self._remote_task_path_map:
            self._apply_path_coloring(source="populate")
        else:
            self._log("Path coloring deferred – context scans still running.", ui_utils.COLOR_INFO)

    def _apply_path_coloring(self, source: str = ""):
        """Re-color the tree. Called after scan completes or after populate (if maps ready)."""
        if self.debug_mode:
            label = f" [{source}]" if source else ""
            self._log(
                f"Applying path coloring{label} – local={len(self._local_task_path_map)} remote={len(self._remote_task_path_map)}",
                ui_utils.COLOR_INFO,
            )
        self._color_subtree(self.task_model.invisibleRootItem())

    def _color_subtree(self, parent_item) -> bool:
        """
        Recursively colors task items and group headers.
        Returns True if ALL descendant tasks are synced.
        Only the name column (col 0) is colored.
          - Task synced   → default color (white)
          - Task missing  → orange
          - Parent all OK → grey
          - Parent any missing → orange
        """
        all_synced = True

        for row in range(parent_item.rowCount()):
            item = parent_item.child(row, 0)
            if item is None:
                continue

            task_data = item.data(Qt.UserRole + 2)
            if isinstance(task_data, dict):
                # Leaf: task item
                task_id = task_data.get("id", "")
                task_name = task_data.get("task_type_name", task_id)
                path = self._resolve_task_path(task_id)
                item.setData(path, Qt.UserRole + 1)
                if self._is_task_synced(task_id):
                    item.setData(None, Qt.ForegroundRole)  # restore theme default
                    item.setToolTip("")
                    if self.debug_mode:
                        self._log(
                            f"  [color] OK   {task_name} ({task_id[:8]}…)  local={self._local_task_path_map.get(task_id, '—')}",
                            ui_utils.COLOR_SUCCESS,
                        )
                else:
                    item.setForeground(QBrush(COLOR_NO_PATH))
                    item.setToolTip("Not synced locally – run your sync tool")
                    all_synced = False
                    if self.debug_mode:
                        self._log(
                            f"  [color] MISS {task_name} ({task_id[:8]}…)  "
                            f"local_map={len(self._local_task_path_map)} entry  in_local={task_id in self._local_task_path_map}  "
                            f"remote_map={len(self._remote_task_path_map)} entry  in_remote={task_id in self._remote_task_path_map}",
                            ui_utils.COLOR_WARNING,
                        )
            else:
                # Group header (Episode / Sequence / Shot / Asset Type / Asset)
                subtree_ok = self._color_subtree(item)
                if subtree_ok:
                    item.setForeground(QBrush(COLOR_PARENT_OK))
                    item.setToolTip("")
                else:
                    item.setForeground(QBrush(COLOR_NO_PATH))
                    item.setToolTip("Some tasks in this group are not synced")
                    all_synced = False

        return all_synced

    def _resolve_task_path(self, task_id: str):
        """Returns the best available browsing path: local first, then remote."""
        if self.local_address:
            path = self._local_task_path_map.get(task_id)
            if path:
                return path
        return self._remote_task_path_map.get(task_id)

    def _is_task_synced(self, task_id: str) -> bool:
        """
        True when the task folder is considered available:
          - local_address configured → must be found in the local scan
          - local_address not set    → found in the remote scan (test/fallback)
        """
        if self.local_address:
            return task_id in self._local_task_path_map
        return task_id in self._remote_task_path_map

    # -------------------------------------------------------------------------
    # Hierarchy helpers
    # -------------------------------------------------------------------------

    def _get_or_create_parent(self, root, hierarchy_path):
        current = root
        cache_key = ()
        for level_type, level_name in hierarchy_path:
            cache_key = cache_key + (level_type, level_name)
            if cache_key in self.hierarchy_cache:
                current = self.hierarchy_cache[cache_key]
            else:
                new_item = QStandardItem(level_name)
                new_item.setEditable(False)
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
        parent.sortChildren(0, Qt.AscendingOrder)
        for row in range(parent.rowCount()):
            child = parent.child(row, 0)
            if child and child.hasChildren():
                self._sort_tree(child)

    # -------------------------------------------------------------------------
    # Thumbnail
    # -------------------------------------------------------------------------

    def _get_thumbnail_icon(self, thumbnail_path_str: str) -> QIcon:
        """Creates a properly scaled QIcon (39x26) from a thumbnail path."""
        pixmap = QPixmap(thumbnail_path_str)
        if pixmap.isNull():
            return QIcon()
        scaled = pixmap.scaled(
            39, 26,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
        return QIcon(scaled)

    def _handle_thumbnail_caching_for_item(self, preview_file_id: str, item: QStandardItem):
        """Sets the thumbnail icon on a tree item, downloading it async if not cached."""
        if not preview_file_id:
            return

        thumbnail_path = ui_utils.get_thumbnail_path(preview_file_id)
        if not thumbnail_path:
            return

        # Already on disk – set icon immediately
        if thumbnail_path.exists():
            icon = self._get_thumbnail_icon(str(thumbnail_path))
            if not icon.isNull():
                item.setIcon(icon)
            self.thumbnail_item_mapping.setdefault(preview_file_id, []).append(item)
            return

        # Need to download. Keep item reference so we can update after download.
        self.thumbnail_item_mapping.setdefault(preview_file_id, [])
        if item not in self.thumbnail_item_mapping[preview_file_id]:
            self.thumbnail_item_mapping[preview_file_id].append(item)

        # Avoid duplicate downloads for the same preview_file_id
        if preview_file_id in self.active_thumbnail_downloads:
            return

        self.active_thumbnail_downloads.add(preview_file_id)
        runnable = ThumbnailRunnable(preview_file_id, str(thumbnail_path), self.thumbnail_signals)
        self.thumbnail_thread_pool.start(runnable)

    def _on_thumbnail_download_finished(self, success: bool, preview_file_id: str):
        self.active_thumbnail_downloads.discard(preview_file_id)
        if not success:
            return

        thumbnail_path = ui_utils.get_thumbnail_path(preview_file_id)
        if not thumbnail_path or not thumbnail_path.exists():
            return

        icon = self._get_thumbnail_icon(str(thumbnail_path))
        if icon.isNull():
            return

        for item in self.thumbnail_item_mapping.get(preview_file_id, []):
            if item.model():  # item still in a live model
                item.setIcon(icon)

        # Refresh the thumbnail label if the downloaded preview belongs to the selected task
        self._emit_refresh_if_still_selected(preview_file_id)

    def _emit_refresh_if_still_selected(self, preview_file_id: str):
        """Re-shows the thumbnail label if the currently selected task matches the download."""
        indexes = self.tasks_tree_view.selectedIndexes()
        if not indexes:
            return
        item = self.task_model.itemFromIndex(indexes[0])
        if not item:
            return
        task_data = item.data(Qt.UserRole + 2)
        if isinstance(task_data, dict) and task_data.get("entity_preview_file_id") == preview_file_id:
            self._show_thumbnail(task_data)

    def _show_thumbnail(self, task_data):
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
    # Task selection
    # -------------------------------------------------------------------------

    def on_task_selection_changed(self, selected, deselected):
        indexes = selected.indexes()
        if not indexes:
            self.task_selection_changed.emit({})
            self._reset_dir_and_file_views()
            return

        item = self.task_model.itemFromIndex(indexes[0])
        if not item:
            return

        task_data = item.data(Qt.UserRole + 2)
        if not isinstance(task_data, dict):
            self.task_selection_changed.emit({})
            self._show_thumbnail(None)
            self._reset_dir_and_file_views()
            return

        self.task_selection_changed.emit(task_data)
        self._show_thumbnail(task_data)

        # Always reset both panels first, then populate only if locally synced.
        self._reset_dir_and_file_views()
        task_id = task_data.get("id", "")
        local_path = self._local_task_path_map.get(task_id) if self.local_address else self._remote_task_path_map.get(task_id)
        self._show_task_directory(local_path)

    def _show_task_directory(self, local_path):
        if not self.directories_tree_view or not hasattr(self, "dir_model"):
            return

        self._reset_files_view()

        if not local_path or not os.path.isdir(local_path):
            self.dir_proxy.setShowContent(False)
            return

        root_index = self.dir_model.setRootPath(local_path)
        self.dir_proxy.setSourceModel(self.dir_model)
        self.dir_proxy.setShowContent(True)

        proxy_root = self.dir_proxy.mapFromSource(root_index)
        self.directories_tree_view.setRootIndex(proxy_root)
        self.directories_tree_view.expandToDepth(0)

    # -------------------------------------------------------------------------
    # Directory selection -> populate files table
    # -------------------------------------------------------------------------

    def on_directory_selection_changed(self, selected, deselected):
        if not hasattr(self, "dir_model") or not hasattr(self, "files_model"):
            return

        indexes = selected.indexes()
        if not indexes:
            self._reset_files_view()
            return

        proxy_index = indexes[0]
        source_index = self.dir_proxy.mapToSource(proxy_index)
        dir_path = self.dir_model.filePath(source_index)

        self._populate_files(dir_path)

    def _populate_files(self, dir_path: str):
        self._reset_files_view()
        if not dir_path or not os.path.isdir(dir_path):
            return

        try:
            entries = sorted(os.scandir(dir_path), key=lambda e: e.name.lower())
        except PermissionError:
            self._log(f"Permission denied: {dir_path}", ui_utils.COLOR_WARNING)
            return

        for entry in entries:
            if entry.is_file():
                try:
                    stat = entry.stat()
                    size_kb = stat.st_size / 1024
                    if size_kb >= 1024:
                        size_str = f"{size_kb / 1024:.1f} MB"
                    else:
                        size_str = f"{size_kb:.1f} KB"
                    mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime(
                        "%Y-%m-%d %H:%M"
                    )
                except OSError:
                    size_str = "?"
                    mtime = "?"

                name_item = QStandardItem(entry.name)
                name_item.setEditable(False)
                name_item.setData(entry.path, Qt.UserRole + 1)
                icon = self.icon_provider.icon(QtCore.QFileInfo(entry.path))
                name_item.setIcon(icon)

                size_item = QStandardItem(size_str)
                size_item.setEditable(False)
                size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

                date_item = QStandardItem(mtime)
                date_item.setEditable(False)

                self.files_model.appendRow([name_item, size_item, date_item])

        if self.files_table_view:
            self.files_table_view.sortByColumn(0, Qt.DescendingOrder)
            self.files_table_view.resizeColumnToContents(1)
            self.files_table_view.resizeColumnToContents(2)

    def _on_file_double_clicked(self, index):
        """Opens the file with the default application."""
        if not index.isValid():
            return
        name_item = self.files_model.item(index.row(), 0)
        if not name_item:
            return
        file_path = name_item.data(Qt.UserRole + 1)
        if file_path and os.path.isfile(file_path):
            ui_utils.open_file(file_path)

    def _on_dir_double_clicked(self, index):
        """Opens the selected directory in the system file explorer."""
        if not index.isValid():
            return
        source_index = self.dir_proxy.mapToSource(index)
        full_path = self.dir_model.filePath(source_index)
        if os.path.isdir(full_path):
            webbrowser.open(os.path.realpath(full_path))
        else:
            self._log(f"Directory does not exist: {full_path}", ui_utils.COLOR_WARNING)

    def _reset_files_view(self):
        if hasattr(self, "files_model"):
            self.files_model.removeRows(0, self.files_model.rowCount())

    def _reset_dir_and_file_views(self):
        if hasattr(self, "dir_proxy"):
            self.dir_proxy.setShowContent(False)
        self._reset_files_view()

    # -------------------------------------------------------------------------
    # Directory context menu
    # -------------------------------------------------------------------------

    def _on_dir_context_menu(self, pos):
        if not self.directories_tree_view or not hasattr(self, "dir_model"):
            return
        proxy_index = self.directories_tree_view.indexAt(pos)
        if not proxy_index.isValid():
            return
        source_index = self.dir_proxy.mapToSource(proxy_index)
        dir_path = self.dir_model.filePath(source_index)
        if not dir_path:
            return

        menu = QtWidgets.QMenu(self)
        action_open = menu.addAction("Open in Explorer")
        action_copy = menu.addAction("Copy Path")

        action = menu.exec(self.directories_tree_view.viewport().mapToGlobal(pos))
        if action == action_open:
            ui_utils.show_in_explorer(dir_path)
        elif action == action_copy:
            QtWidgets.QApplication.clipboard().setText(dir_path)

    # -------------------------------------------------------------------------
    # Files context menu
    # -------------------------------------------------------------------------

    def _on_file_context_menu(self, pos):
        if not self.files_table_view or not hasattr(self, "files_model"):
            return
        index = self.files_table_view.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        name_item = self.files_model.item(row, 0)
        if not name_item:
            return
        file_path = name_item.data(Qt.UserRole + 1)
        if not file_path:
            return

        menu = QtWidgets.QMenu(self)
        action_open = menu.addAction("Open")
        action_reveal = menu.addAction("Show in Explorer")
        action_copy = menu.addAction("Copy Path")
        menu.addSeparator()
        action_publish = menu.addAction("Publish to Kitsu...")

        action = menu.exec(self.files_table_view.viewport().mapToGlobal(pos))
        if action == action_open:
            ui_utils.open_file(file_path)
        elif action == action_reveal:
            ui_utils.show_in_explorer(file_path)
        elif action == action_copy:
            QtWidgets.QApplication.clipboard().setText(file_path)
        elif action == action_publish:
            task_data = self._get_selected_task()
            if task_data:
                self.publish_to_kitsu(task_data, prefill_path=file_path)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_selected_task(self):
        indexes = self.tasks_tree_view.selectedIndexes()
        if not indexes:
            return None
        item = self.task_model.itemFromIndex(indexes[0])
        if not item:
            return None
        data = item.data(Qt.UserRole + 2)
        return data if isinstance(data, dict) else None

    def _get_selected_task_local_path(self):
        indexes = self.tasks_tree_view.selectedIndexes()
        if not indexes:
            return None
        item = self.task_model.itemFromIndex(indexes[0])
        if not item:
            return None
        return item.data(Qt.UserRole + 1)

    # -------------------------------------------------------------------------
    # Double-click -> open Kitsu in browser
    # -------------------------------------------------------------------------

    def _on_task_double_clicked(self, index):
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
    # Task context menu
    # -------------------------------------------------------------------------

    def on_task_context_menu(self, pos):
        task_data = self._get_selected_task()
        if not task_data:
            return

        menu = QtWidgets.QMenu(self)
        action_publish = menu.addAction("Publish to Kitsu...")
        action_comment = menu.addAction("Add Comment / Feedback...")
        menu.addSeparator()

        local_path = self._get_selected_task_local_path()
        action_reveal = None
        if local_path and os.path.isdir(local_path):
            action_reveal = menu.addAction("Show Task Folder in Explorer")

        menu.addSeparator()
        action_open_web = menu.addAction("Open in Kitsu (Browser)")

        action = menu.exec(self.tasks_tree_view.viewport().mapToGlobal(pos))

        if action == action_publish:
            self.publish_to_kitsu(task_data)
        elif action == action_comment:
            self.add_comment_to_task(task_data)
        elif action_reveal and action == action_reveal:
            ui_utils.show_in_explorer(local_path)
        elif action == action_open_web:
            self._on_task_double_clicked(self.tasks_tree_view.selectedIndexes()[0])

    # -------------------------------------------------------------------------
    # Publish
    # -------------------------------------------------------------------------

    def publish_to_kitsu(self, task_data=None, prefill_path=None):
        if task_data is None:
            task_data = self._get_selected_task()
        if not task_data:
            self._log("No task selected.", ui_utils.COLOR_WARNING)
            return

        task_id = task_data.get("id")
        if task_id:
            success, fresh = gazu_api.get_task(task_id)
            if success and fresh:
                task_data = self._merge_task_data(task_data, fresh)

        status_ok, all_statuses = gazu_api.get_task_statuses()
        if not status_ok or not all_statuses:
            self._log("Failed to fetch task statuses.", ui_utils.COLOR_ERROR)
            return

        dlg = PublisherDialog(task_data, all_statuses, parent=self.main_window)
        if prefill_path:
            dlg.set_file_path(prefill_path)
        result = dlg.exec()

        if result != QtWidgets.QDialog.Accepted:
            self._log("Publish cancelled by user.", ui_utils.COLOR_INFO)
            return

        file_path = dlg.get_file_path()
        if not file_path or not os.path.isfile(file_path):
            self._log("Publish cancelled: no valid file selected.", ui_utils.COLOR_WARNING)
            return

        selected_status = dlg.get_selected_status()
        if not selected_status:
            self._log("No status selected.", ui_utils.COLOR_ERROR)
            return

        comment = dlg.get_comment()
        file_name = os.path.basename(file_path)

        self._log(f"Added to publish queue '{file_name}'...", ui_utils.COLOR_INFO)

        from .publisher_manager_dialog import PublisherManagerDialog
        file_data = {
            'file_name': file_name,
            'file_path': file_path,
            'task_data': task_data,
            'status_dict': selected_status,
            'comment': comment,
        }

        if not hasattr(self.main_window, "publisher_manager_dialog") or \
                self.main_window.publisher_manager_dialog is None:
            self.main_window.publisher_manager_dialog = PublisherManagerDialog([], self.main_window)

        self.main_window.publisher_manager_dialog.add_files_to_queue([file_data])
        self.main_window.publisher_manager_dialog.show()
        ui_utils.position_next_to_parent(self.main_window.publisher_manager_dialog, self.main_window)
        self.main_window.publisher_manager_dialog.raise_()
        self.main_window.publisher_manager_dialog.activateWindow()

    # -------------------------------------------------------------------------
    # Comment / feedback
    # -------------------------------------------------------------------------

    def add_comment_to_task(self, task_data=None):
        if task_data is None:
            task_data = self._get_selected_task()
        if not task_data:
            self._log("No task selected.", ui_utils.COLOR_WARNING)
            return

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
    # Merge helper
    # -------------------------------------------------------------------------

    @staticmethod
    def _merge_task_data(base, fresh):
        merged = dict(base)
        if "task_status_id" in fresh:
            merged["task_status_id"] = fresh["task_status_id"]
        entity = fresh.get("entity", {})
        if isinstance(entity, dict) and "name" in entity:
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

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------

    def cleanup(self):
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
        if self.directories_tree_view:
            try:
                self.directories_tree_view.selectionModel().selectionChanged.disconnect(
                    self.on_directory_selection_changed
                )
            except (TypeError, RuntimeError):
                pass
        self.thumbnail_thread_pool.clear()
        for _scan_thread in (self._remote_scan_thread, self._local_scan_thread):
            if _scan_thread is not None:
                try:
                    _scan_thread.quit()
                    _scan_thread.wait(2000)
                except RuntimeError:
                    pass


# ---------------------------------------------------------------------------
# Comment-only dialog
# ---------------------------------------------------------------------------

class _CommentDialog(QtWidgets.QDialog):
    def __init__(self, task_data, all_statuses, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Comment / Feedback")
        self.setMinimumWidth(420)

        layout = QtWidgets.QVBoxLayout(self)

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

        comment_group = QtWidgets.QGroupBox("Comment")
        comment_vbox = QtWidgets.QVBoxLayout()
        self.comment_edit = QtWidgets.QTextEdit()
        self.comment_edit.setPlaceholderText("Enter your feedback here...")
        self.comment_edit.setMinimumHeight(80)
        comment_vbox.addWidget(self.comment_edit)
        comment_group.setLayout(comment_vbox)
        layout.addWidget(comment_group)

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
