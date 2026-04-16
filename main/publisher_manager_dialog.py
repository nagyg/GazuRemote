from PySide6 import QtWidgets, QtCore, QtGui
import os
import webbrowser
from services import ui_utils

class PublisherManagerDialog(QtWidgets.QDialog):
    def __init__(self, selected_files_data, parent=None):
        """
        selected_files_data: list of dicts with keys:
           'file_name', 'file_path', 'task_data', 'status_dict', 'comment'
        """
        super().__init__(parent)
        self.selected_files_data = selected_files_data
        self._site_config = parent.site_config if parent and hasattr(parent, "site_config") else None

        self.setWindowFlag(QtCore.Qt.Tool)
        self.setMinimumWidth(650)
        self.resize(650, 600)

        # Main layout
        self.main_layout = QtWidgets.QVBoxLayout(self)

        # Build Table
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Filename", "Target Task", "Status", "Progress", "Kitsu"])

        # Stretch columns nicely
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.Fixed)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.Fixed)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 80)

        # Consistency Styling matching the rest of the App
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(QtCore.Qt.NoFocus)

        self.progress_labels = []

        # Queue Management State
        self.queue = []  # List of tuples: (row_idx, args_dict)
        self.active_workers = {}  # thread: worker
        self.max_threads = 2
        self.completed_count = 0
        self.is_publishing = False
        self.failed_items = []

        # Initialize empty files data list
        self.selected_files_data = []

        self.main_layout.addWidget(self.table)

        # Get Kitsu metadata
        from services import gazu_api
        success, self.kitsu_base_url = gazu_api.get_kitsu_base_url()

        # Log Widget
        self.log_widget = QtWidgets.QTextEdit()
        self.log_widget.setReadOnly(True)
        self.log_widget.setMinimumSize(QtCore.QSize(0, 150))
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.log_widget.setSizePolicy(sizePolicy)
        self.log_widget.setPlaceholderText("Console output will appear here...")
        self.log_widget.setStyleSheet("""
            QTextEdit {
                color: #A5A5A5;
                font-family: "Segoe UI";
                font-size: 9pt;
            }
        """)
        self.main_layout.addWidget(self.log_widget)

        # Button Box
        self.button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        self.button_box.rejected.connect(self.hide)

        self.main_layout.addWidget(self.button_box)

        # Process initial files
        self.add_files_to_queue(selected_files_data)

    def _log(self, message, color_hex=ui_utils.COLOR_INFO):
        ui_utils.log_to_widget(self.log_widget, message, color_hex)

    def add_files_to_queue(self, new_files_data):
        start_row = self.table.rowCount()
        self.table.setRowCount(start_row + len(new_files_data))

        for i, item_data in enumerate(new_files_data):
            row_idx = start_row + i
            self.selected_files_data.append(item_data)

            file_name_item = QtWidgets.QTableWidgetItem(item_data['file_name'])
            file_name_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)

            task_type_name = item_data['task_data'].get('task_type_name', 'Unknown')
            entity_name = item_data['task_data'].get('entity_name', 'Unknown')
            target_task_str = f"{entity_name} - {task_type_name}"
            task_item = QtWidgets.QTableWidgetItem(target_task_str)
            task_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)

            # Status Label
            status_dict = item_data.get('status_dict', {})
            status_name = status_dict.get('name', 'Unknown')
            status_item = QtWidgets.QTableWidgetItem(status_name)

            # Apply color from database if available
            status_color = status_dict.get('color')
            if status_color:
                status_item.setForeground(QtGui.QBrush(QtGui.QColor(status_color)))

            status_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            status_item.setTextAlignment(QtCore.Qt.AlignCenter)

            # Progress Label
            progress_lbl = QtWidgets.QLabel("Queued")
            progress_lbl.setAlignment(QtCore.Qt.AlignCenter)
            progress_lbl.setStyleSheet("color: #FFFFFF;")
            self.progress_labels.append(progress_lbl)

            # Kitsu Link
            task_data = item_data['task_data']
            project_id = task_data.get('project_id')
            kitsu_url = ui_utils.get_kitsu_task_url(getattr(self, 'kitsu_base_url', ''), project_id, task_data)

            link_btn = QtWidgets.QPushButton("Open")
            link_btn.setToolTip(kitsu_url)
            link_btn.setCursor(QtCore.Qt.PointingHandCursor)
            link_btn.setStyleSheet("""
                QPushButton {
                    text-decoration: none;
                    border: none;
                    background: transparent;
                }
            """)
            link_btn.clicked.connect(lambda checked=False, url=kitsu_url: webbrowser.open(url))

            # Set items
            self.table.setItem(row_idx, 0, file_name_item)
            self.table.setItem(row_idx, 1, task_item)
            self.table.setItem(row_idx, 2, status_item)
            self.table.setCellWidget(row_idx, 3, progress_lbl)
            self.table.setCellWidget(row_idx, 4, link_btn)

            # Immediately append to queue
            selected_status = item_data.get('status_dict', {})
            comment_text = item_data.get('comment', '')
            formatted_comment = ui_utils.format_comment_html(comment_text)

            self.queue.append((row_idx, {
                'task_data': item_data['task_data'],
                'task_status': selected_status,
                'comment': formatted_comment,
                'file_path': item_data['file_path']
            }))

            # Log addition if not initial setup
            if start_row > 0:
                self._log(f"Added to publisher: {item_data['file_name']}", ui_utils.COLOR_INFO)

        self.setWindowTitle(f"Publisher Manager ({len(self.selected_files_data)} files)")

        self._start_available_workers()

    def _start_available_workers(self):
        self.is_publishing = True

        # Start workers up to max_threads limit
        available_slots = self.max_threads - len(self.active_workers)
        for _ in range(min(available_slots, len(self.queue))):
            self._start_next_in_queue()

    def _start_next_in_queue(self):
        if not self.queue:
            self._check_all_completed()
            return

        row_idx, work_kwargs = self.queue.pop(0)

        file_name = self.selected_files_data[row_idx]['file_name']
        self._log(f"Publishing... {file_name}", ui_utils.COLOR_WARNING)

        # Update UI
        lbl = self.progress_labels[row_idx]
        lbl.setText("Publishing...")
        lbl.setStyleSheet(f"color: {ui_utils.COLOR_WARNING};")

        # Import lazily to avoid circular dependency
        from .remote_tasks_widget import PublishWorker

        thread = QtCore.QThread(self)
        worker = PublishWorker(
            task=work_kwargs['task_data'],
            task_status=work_kwargs['task_status'],
            comment=work_kwargs['comment'],
            file_path=work_kwargs['file_path']
        )
        worker.moveToThread(thread)

        # Store worker
        self.active_workers[thread] = worker

        worker.finished.connect(lambda s, r, idx=row_idx, w=worker, t=thread: self._on_worker_finished(s, r, idx, w, t))
        thread.started.connect(worker.run)
        thread.finished.connect(thread.deleteLater)

        thread.start()

    def _on_worker_finished(self, success, result, row_idx, worker, thread):
        # UI update
        lbl = self.progress_labels[row_idx]
        file_name = self.selected_files_data[row_idx]['file_name']

        if success:
            lbl.setText("Success")
            lbl.setStyleSheet(f"color: {ui_utils.COLOR_SUCCESS};")
            self._log(f"Success: {file_name}", ui_utils.COLOR_SUCCESS)
        else:
            lbl.setText("Failed")
            lbl.setStyleSheet(f"color: {ui_utils.COLOR_ERROR};")

            self.failed_items.append((file_name, str(result)))
            self._log(f"Failed: {file_name} - {str(result)}", ui_utils.COLOR_ERROR)

        # Cleanup worker
        worker.deleteLater()
        thread.quit()
        self.active_workers.pop(thread, None)

        self.completed_count += 1

        # Start next if available
        self._start_next_in_queue()

    def _check_all_completed(self):
        # Done when queue is empty AND no workers are running
        if not self.queue and not self.active_workers:
            self.is_publishing = False

            # Show summary dialog if there were failures
            if self.failed_items:
                msg_text = "Publishing finished, but some files encountered errors:\n\n"
                for fname, err in self.failed_items:
                    msg_text += f"• {fname}: {err}\n"
                QtWidgets.QMessageBox.warning(self, "Publish Issues", msg_text)
                self.failed_items = []
