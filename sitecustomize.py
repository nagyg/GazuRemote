"""Embeddable Python ignores PYTHONPATH (python312._pth isolates sys.path).
This module is copied into Python312\\Lib\\site-packages by install.cmd on every
run, so it is auto-imported by `site` at interpreter startup, restoring normal
PYTHONPATH behavior for Fusion (FUSION_PYTHON3_HOME points at this interpreter).
"""
import os
import sys

_pythonpath = os.environ.get("PYTHONPATH", "")
for _entry in reversed(_pythonpath.split(os.pathsep)):
    if _entry and _entry not in sys.path:
        sys.path.insert(0, _entry)
