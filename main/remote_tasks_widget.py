import datetime
import json
import os
import re
import shutil
import traceback
import webbrowser
from pathlib import Path

from PySide6 import QtWidgets, QtCore
from PySide6.QtCore import Qt, QObject, Signal, QThreadPool, QRunnable, QMimeData
from PySide6.QtGui import (
    QStandardItemModel, QStandardItem, QBrush, QColor, QFont, QPixmap, QIcon
)
from PySide6.QtWidgets import QFileIconProvider, QInputDialog, QMessageBox

from services import gazu_api, ui_utils
from .publisher_dialog import PublisherDialog


# ---------------------------------------------------------------------------
# Colors for path-availability feedback
# ---------------------------------------------------------------------------
COLOR_NO_PATH   = QColor(150, 50, 50)   # red – task/parent with unsynced files
COLOR_PARENT_OK = QColor(50, 150, 50)  # green – all tasks found under this parent


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

        # task_id -> folder_path, built from templates.json
        self._remote_task_path_map: dict = {}
        self._local_task_path_map: dict = {}
        # templates.json cache – loaded once from server, invalidated on mtime change
        self._templates: list = []
        self._templates_file_mtime: float = 0.0

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

    # -------------------------------------------------------------------------
    # Template-based path map
    # -------------------------------------------------------------------------

    def refresh_path_map(self):
        """Invalidates the templates cache so the next populate reloads from disk."""
        self._templates_file_mtime = 0.0
        self._remote_task_path_map = {}
        self._local_task_path_map = {}

    def _load_templates(self) -> list:
        """
        Loads templates.json from the VPN server path (single source of truth).
        Cached by file mtime – only re-reads when the file changes.
        Returns an empty list with a warning log if the file is missing.
        """
        if not self.remote_address or not self.project_data:
            return []
        project_name = self.project_data.get("name", "")
        templates_path = os.path.join(
            self.remote_address, project_name, ".gazu", "templates", "templates.json"
        )
        try:
            mtime = os.path.getmtime(templates_path)
        except OSError:
            if self._templates:
                return self._templates  # serve stale cache if server temporarily unreachable
            self._log(
                f"templates.json not found – path coloring unavailable: {templates_path}",
                ui_utils.COLOR_WARNING,
            )
            return []
        if mtime != self._templates_file_mtime:
            try:
                with open(templates_path, "r", encoding="utf-8") as fh:
                    self._templates = json.load(fh)
                self._templates_file_mtime = mtime
                self._log(
                    f"Loaded {len(self._templates)} template(s) from server.",
                    ui_utils.COLOR_INFO,
                )
            except Exception as e:
                self._log(f"Failed to read templates.json: {e}", ui_utils.COLOR_WARNING)
        return self._templates

    def _resolve_template_path(self, template_string: str, task: dict) -> str:
        """
        Resolves {placeholder} tokens in a template string to a relative OS path.
        Empty segments (e.g. {episode} on a non-tvshow project) are dropped.
        """
        project_type = (self.project_data.get("production_type") or "").lower()
        replacements = {
            "project_name":    self.project_data.get("name", ""),
            "asset_type":      task.get("entity_type_name") or "",
            "episode":         task.get("episode_name") if project_type == "tvshow" else "",
            "sequence":        task.get("sequence_name") if project_type in ("tvshow", "featurefilm", "short") else "",
            "entity":          task.get("entity_name") or "",
            "task_type":       task.get("task_type_name") or "",
            "task_type_short": task.get("task_type_short_name") or task.get("task_type_name") or "",
        }
        resolved = re.sub(
            r"\{(\w+)\}",
            lambda m: replacements.get(m.group(1), m.group(0)),
            template_string,
        )
        # Normalise to OS-native separators and drop empty segments
        parts = [p for p in resolved.replace("\\", "/").split("/") if p]
        return os.path.join(*parts) if parts else ""

    def _build_path_map(self, tasks: list):
        """
        Builds task_id → path maps from templates.json + task metadata.
        No filesystem walk – pure JSON + string operations + os.path.isdir on
        local paths only.
        """
        templates = self._load_templates()
        if not templates:
            self._remote_task_path_map = {}
            self._local_task_path_map = {}
            return

        tmpl_by_name = {
            t["name"]: t
            for t in templates
            if t.get("name") and t.get("template")
        }

        local_map: dict = {}
        remote_map: dict = {}

        for task in tasks:
            task_id = task.get("id", "")
            task_type_name = task.get("task_type_name", "")
            task_type_short = task.get("task_type_short_name") or task_type_name
            tmpl = tmpl_by_name.get(task_type_name)
            if not tmpl:
                if self.debug_mode:
                    self._log(
                        f"  [path] NO TEMPLATE for task_type_name='{task_type_name}' "
                        f"task_id={task_id[:8]}",
                        ui_utils.COLOR_WARNING,
                    )
                continue
            rel_path = self._resolve_template_path(tmpl["template"], task)
            if not rel_path:
                continue

            if self.remote_address:
                remote_map[task_id] = os.path.join(self.remote_address, rel_path)

            if self.local_address:
                local_full = os.path.join(self.local_address, rel_path)
                found = os.path.isdir(local_full)
                if self.debug_mode:
                    self._log(
                        f"  [path] {task_type_name} ({task_type_short}) | rel={rel_path} | "
                        f"local={local_full} | found={found}",
                        ui_utils.COLOR_SUCCESS if found else ui_utils.COLOR_WARNING,
                    )
                if found:
                    local_map[task_id] = local_full

        self._remote_task_path_map = remote_map
        self._local_task_path_map = local_map

        synced = len(local_map)
        total = len(remote_map)
        self._log(
            f"Path map built – {synced}/{total} task folder(s) synced locally.",
            ui_utils.COLOR_SUCCESS,
        )

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
        hdr = self.tasks_tree_view.header()
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)
        hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        self.tasks_tree_view.setColumnWidth(0, 200)
        self.tasks_tree_view.setColumnWidth(1, 80)
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
            type_item.setTextAlignment(Qt.AlignCenter)

            status_item = QStandardItem(task_status)
            status_item.setEditable(False)
            status_item.setTextAlignment(Qt.AlignCenter)
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
        # Expand only top-level items (Episode / Asset Type); task rows stay collapsed
        for i in range(root.rowCount()):
            self.tasks_tree_view.expand(self.task_model.indexFromItem(root.child(i)))
        self._build_path_map(tasks)
        self._apply_path_coloring(source="populate")

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
        True when the task folder exists locally.
        Always checks local_task_path_map (folders confirmed via os.path.isdir).
        If local_address is not configured the user has no local drive → not synced.
        """
        if self.local_address:
            return task_id in self._local_task_path_map
        return False

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
                placeholder_type.setTextAlignment(Qt.AlignCenter)
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

        def _expand_once(path):
            self.directories_tree_view.expandToDepth(0)
            try:
                self.dir_model.directoryLoaded.disconnect(_expand_once)
            except RuntimeError:
                pass

        self.dir_model.directoryLoaded.connect(_expand_once)

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
                if any(entry.name.lower().endswith(ext) for ext in ui_utils.HIDDEN_EXTENSIONS):
                    continue
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
        """Opens the file: DCC launch for known extensions, OS default otherwise."""
        if not index.isValid():
            return
        name_item = self.files_model.item(index.row(), 0)
        if not name_item:
            return
        file_path = name_item.data(Qt.UserRole + 1)
        if not file_path or not os.path.isfile(file_path):
            return

        from . import dcc_launcher
        config_service = getattr(self.main_window, "config_service", None)
        app_root = getattr(self.main_window, "_app_root", None)

        if config_service and app_root:
            if dcc_launcher.launch_with_dcc(file_path, config_service, app_root, self._log):
                return

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

        file_name = os.path.basename(file_path)

        menu = QtWidgets.QMenu(self)
        action_open = menu.addAction("Open")
        action_reveal = menu.addAction("Show in Explorer")
        action_copy = menu.addAction("Copy Path")
        menu.addSeparator()
        action_rename = menu.addAction("Rename")
        action_delete = menu.addAction("Delete")

        # Kitsu Publisher – media files only
        action_publish = None
        media_extensions = ('.mov', '.mp4', '.jpg', '.png')
        if file_name.lower().endswith(media_extensions):
            menu.addSeparator()
            action_publish = menu.addAction("Publish to Kitsu...")

        # Create Next Version – workfiles only
        action_version_up = None
        if any(file_name.lower().endswith(ext) for ext in ui_utils.WORKFILE_EXTENSIONS):
            if action_publish is None:
                menu.addSeparator()
            action_version_up = menu.addAction("Create Next Version")

        action = menu.exec(self.files_table_view.viewport().mapToGlobal(pos))
        if action == action_open:
            from . import dcc_launcher
            config_service = getattr(self.main_window, "config_service", None)
            app_root = getattr(self.main_window, "_app_root", None)
            if config_service and app_root:
                if dcc_launcher.launch_with_dcc(file_path, config_service, app_root, self._log):
                    return
            ui_utils.open_file(file_path)
        elif action == action_reveal:
            ui_utils.show_in_explorer(file_path)
        elif action == action_copy:
            QtWidgets.QApplication.clipboard().setText(file_path)
        elif action == action_rename:
            self._rename_file(file_path)
        elif action == action_delete:
            self._delete_file(file_path)
        elif action_publish and action == action_publish:
            task_data = self._get_selected_task()
            if task_data:
                self.publish_to_kitsu(task_data, prefill_path=file_path)
        elif action_version_up and action == action_version_up:
            self._version_up_file(file_path)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_current_directory_path(self):
        """Returns the full path of the currently selected directory."""
        if not self.directories_tree_view or not hasattr(self, "dir_model"):
            return None
        indexes = self.directories_tree_view.selectionModel().selectedIndexes()
        if not indexes:
            return None
        source_index = self.dir_proxy.mapToSource(indexes[0])
        return self.dir_model.filePath(source_index)

    def _refresh_files_view(self):
        """Re-populates the files table from the currently selected directory."""
        dir_path = self._get_current_directory_path()
        if dir_path:
            self._populate_files(dir_path)

    def _rename_file(self, file_path: str):
        """Renames a file after user input."""
        old_name = os.path.basename(file_path)
        dir_path = os.path.dirname(file_path)

        dialog = QInputDialog(self)
        dialog.setWindowTitle("Rename File")
        dialog.setLabelText("New name:")
        dialog.setTextValue(old_name)
        dialog.setInputMode(QInputDialog.TextInput)
        dialog.resize(360, dialog.height())

        if not dialog.exec():
            return
        new_name = dialog.textValue().strip()
        if not new_name or new_name == old_name:
            return

        new_path = os.path.join(dir_path, new_name)
        try:
            os.rename(file_path, new_path)
            self._log(f"Renamed '{old_name}' → '{new_name}'", ui_utils.COLOR_SUCCESS)
            self._refresh_files_view()
        except OSError as e:
            self._log(f"Rename failed: {e}", ui_utils.COLOR_ERROR)

    def _delete_file(self, file_path: str):
        """Deletes a file after confirmation."""
        file_name = os.path.basename(file_path)
        reply = QMessageBox.warning(
            self,
            "Confirm Deletion",
            f"Are you sure you want to permanently delete '{file_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            os.remove(file_path)
            self._log(f"Deleted '{file_name}'", ui_utils.COLOR_SUCCESS)
            self._refresh_files_view()
        except OSError as e:
            self._log(f"Delete failed: {e}", ui_utils.COLOR_ERROR)

    def _version_up_file(self, file_path: str):
        """Creates an incremented copy of a workfile (e.g. _v001 → _v002)."""
        file_name = os.path.basename(file_path)
        dir_path = os.path.dirname(file_path)

        matches = list(re.finditer(r"[._]v(\d{3})", file_name))
        if not matches:
            self._log(
                f"No version number found in '{file_name}'. Expected format: '..._v001...'",
                ui_utils.COLOR_WARNING,
            )
            return

        match = matches[-1]
        prefix_char = match.group(0)[0]
        next_ver = int(match.group(1)) + 1
        new_ver_str = f"{prefix_char}v{next_ver:03d}"
        new_name = file_name[: match.start()] + new_ver_str + file_name[match.end():]
        new_path = os.path.join(dir_path, new_name)

        if os.path.exists(new_path):
            self._log(f"Version already exists: {new_name}", ui_utils.COLOR_WARNING)
            return

        try:
            shutil.copy2(file_path, new_path)
            self._log(f"Created next version: {new_name}", ui_utils.COLOR_SUCCESS)
            self._refresh_files_view()
        except OSError as e:
            self._log(f"Version up failed: {e}", ui_utils.COLOR_ERROR)

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
