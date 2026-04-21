"""Show.py - Gazu context viewer.

Read-only: displays cached context data stored in the comp (CustomData/Gazu).
If no cache exists, shows a clear message to run Reload Context.

All comp updates (API fetch, path maps, settings) are Reload.py's responsibility.
"""
import os
import json
import sys

try:
    from PySide2 import QtWidgets, QtCore, QtGui
    HAS_QT = True
except ImportError:
    try:
        from PySide6 import QtWidgets, QtCore, QtGui
        HAS_QT = True
    except ImportError:
        HAS_QT = False


# ---------------------------------------------------------------------------
# Fusion helper
# ---------------------------------------------------------------------------

def get_comp():
    try:
        return comp
    except NameError:
        try:
            return fusion.GetCurrentComp()
        except NameError:
            return None


# ---------------------------------------------------------------------------
# Display formatter
# ---------------------------------------------------------------------------

def _format_context_display(gazu_data, path_prefs=None):
    """Format cached Gazu comp data (comp.GetData('Gazu')) into readable text."""
    if not gazu_data:
        return (
            "No Gazu context found in this composition.\n\n"
            "Please run:  Comp  \u203a  Gazu  \u203a  Reload Context\n\n"
            "This will:\n"
            "  1. Find the nearest .gazu_context file\n"
            "  2. Fetch live data from the Kitsu API\n"
            "  3. Update composition settings (FPS, resolution, frame range)\n"
            "  4. Store context data for use in expressions"
        )

    ctx = gazu_data.get('Context', {}) or {}

    def v(*keys):
        for k in keys:
            val = gazu_data.get(k)
            if val is None:
                val = ctx.get(k)
            if val is not None and val != '' and val != {}:
                return str(val)
        return "\u2014"

    def kv(key, value):
        return f"  {key:<20}>  {value}"

    lines = []

    # --- Project Context ---
    lines.append("[ Context ]")
    lines.append("")
    lines.append(kv("Project", v('Project', 'project_name')))
    ep = v('Episode', 'episode_name')
    if ep != "\u2014":
        lines.append(kv("Episode", ep))
    lines.append(kv("Sequence", v('Sequence', 'sequence_name')))
    entity_type = v('entity_type')
    shot_label  = "Asset" if entity_type == "Asset" else "Shot"
    lines.append(kv(shot_label, v('Shot', 'Asset', 'Entity', 'entity_name')))
    task      = v('Task', 'task_short_name')
    task_full = v('task_name')
    task_val  = task
    if task_full != "\u2014" and task_full.lower() != task.lower():
        task_val += f"  ({task_full})"
    lines.append(kv("Task", task_val))
    lines.append(kv("Status", v('task_status')))
    lines.append("")

    # --- Technical ---
    lines.append("[ Technical ]")
    lines.append("")
    f_in  = v('frame_in')
    f_out = v('frame_out')
    nb    = v('entity_nb_frames')
    if f_in != "\u2014" and f_out != "\u2014":
        frame_val = f"{f_in} \u2013 {f_out}"
        if nb != "\u2014":
            frame_val += f"  ({nb} frames)"
        lines.append(kv("Frames", frame_val))
    ed     = ctx.get('entity_data', {}) or {}
    nested = ed.get('data', {}) or {}
    fps = ed.get('fps') or nested.get('fps') or gazu_data.get('fps')
    res = ed.get('resolution') or nested.get('resolution') or gazu_data.get('resolution')
    lines.append(kv("FPS", fps or chr(8212)))
    lines.append(kv("Resolution", res or chr(8212)))
    lines.append("")

    # --- Paths ---
    lines.append("[ Paths ]")
    lines.append("")
    lines.append(kv("Mountpoint", v('project_mountpoint')))
    if path_prefs:
        gazu_keys = {k.rstrip(':'): pv
                     for k, pv in path_prefs.items()
                     if 'Gazu' in k and k.rstrip(':') != 'project_mountpoint'}
        for pk in sorted(gazu_keys):
            lines.append(kv(pk, gazu_keys[pk]))
    lines.append("")

    # --- IDs ---
    lines.append("[ IDs ]")
    lines.append("")
    lines.append(kv("project_id", ctx.get('project_id', v('project_id'))))
    lines.append(kv("task_id", ctx.get('task_id', v('task_id'))))

    # --- Custom (extra entity_data fields not shown above) ---
    _standard_ed_keys = {'fps', 'resolution', 'frame_in', 'frame_out', 'data'}
    all_ed = {}
    if ed:
        all_ed.update({k: val for k, val in ed.items()
                       if k not in _standard_ed_keys and val is not None})
    if nested:
        all_ed.update({k: val for k, val in nested.items()
                       if k not in _standard_ed_keys and val is not None})
    if all_ed:
        lines.append("")
        lines.append("[ Custom ]")
        lines.append("")
        for k, val in sorted(all_ed.items()):
            clean = str(k).replace(" ", "_").replace("-", "_")
            lines.append(kv(clean, val))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

if HAS_QT:
    class _ContextDialog(QtWidgets.QDialog):

        def __init__(self, current_comp, parent=None):
            super().__init__(parent)
            self._comp = current_comp
            self._build_ui()
            self._show_cache()

        def _build_ui(self):
            self.setWindowTitle("Gazu Context")
            self.resize(600, 640)
            try:
                icon_path = fusion.MapPath(r"GazuData:Python/images/gazu_fill.ico")
                if icon_path and os.path.exists(icon_path):
                    self.setWindowIcon(QtGui.QIcon(icon_path))
            except Exception:
                pass

            layout = QtWidgets.QVBoxLayout(self)
            layout.setSpacing(6)

            self._status_lbl = QtWidgets.QLabel("")
            self._status_lbl.setStyleSheet("color: #aaaaaa; font-size: 10px; padding: 2px 0;")
            layout.addWidget(self._status_lbl)

            self._text = QtWidgets.QTextEdit()
            self._text.setReadOnly(True)
            self._text.setFont(QtGui.QFont("Courier New", 10))
            layout.addWidget(self._text)

            btn_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
            btn_box.accepted.connect(self.accept)
            layout.addWidget(btn_box)

        def _show_cache(self):
            gazu_data  = self._comp.GetData("Gazu") if self._comp else None
            last_error = (gazu_data or {}).get('api_error_msg', '') or ''
            path_prefs = None
            if self._comp and gazu_data:
                try:
                    path_prefs = self._comp.GetPrefs("Comp.Paths.Map") or {}
                except Exception:
                    pass
            display_text = _format_context_display(gazu_data, path_prefs)
            if last_error:
                sep = "\u2500" * 52
                display_text = "[ API hiba ]\n\n  " + last_error + "\n\n" + sep + "\n\n" + display_text
            self._text.setPlainText(display_text)
            if last_error:
                self._status_lbl.setText(f"\u26a0 API hiba: {last_error}")
                self._status_lbl.setStyleSheet("color: #cc4444; font-size: 10px; padding: 2px 0;")
            elif gazu_data:
                self._status_lbl.setText("Saved in .comp file  (CustomData \u203a Gazu)  \u2014  run Reload Context to update")
                self._status_lbl.setStyleSheet("color: #88cc88; font-size: 10px; padding: 2px 0;")
            else:
                self._status_lbl.setText("No context \u2014 run Reload Context to populate")
                self._status_lbl.setStyleSheet("color: #ccaa44; font-size: 10px; padding: 2px 0;")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def show_context_popup():
    current_comp = get_comp()
    if not current_comp:
        print("Error: No active Fusion composition.")
        return

    if HAS_QT:
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        dlg = _ContextDialog(current_comp)
        if hasattr(dlg, "exec"):
            dlg.exec()
        else:
            dlg.exec_()
    else:
        gazu_data = current_comp.GetData("Gazu") or {}
        try:
            msg = _format_context_display(gazu_data)
        except Exception:
            msg = str(gazu_data)
        current_comp.AskUser("Gazu Context", {
            1: {"Name": "Data", 1: "Text", 2: "Text",
                "ReadOnly": True, "Font": "Fixed", "Lines": 30, "Default": msg}
        })


if __name__ == "__main__":
    show_context_popup()
