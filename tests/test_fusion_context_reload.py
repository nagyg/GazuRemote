import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


RELOAD_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "dcc" / "Fusion" / "Gazu" / "Scripts" / "Comp"
    / "Gazu" / "Context" / "Reload.py"
)


class FusionContextReloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="Gazu Remote ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lib = self.root / "Lib"
        self.scripts = self.root / "scripts"
        self.lib.mkdir()
        self.scripts.mkdir()
        (self.root / ".gazu_context").write_text(json.dumps({
            "project_id": "project-id",
            "task_id": "task-id",
        }), encoding="utf-8")
        self.comp = Mock()
        self.comp.GetAttrs.return_value = {
            "COMPS_FileName": str(self.root / "test.comp"),
        }
        self.fusion = Mock()
        self.output = io.StringIO()
        self.paths = os.pathsep.join((str(self.lib), str(self.scripts)))

    def run_reload(self, on_path=True):
        # sitecustomize.py puts PYTHONPATH on sys.path in the real install;
        # here sys.path is set directly to emulate that.
        search_path = [str(self.lib), str(self.scripts)] if on_path else []
        with patch.dict(os.environ, {
            "GAZULIB": self.paths,
            "PYTHONPATH": self.paths,
        }), patch.object(sys, "path", search_path + list(sys.path)), \
                patch.dict(sys.modules):
            sys.modules.pop("gazu_api", None)
            with contextlib.redirect_stdout(self.output), \
                    contextlib.redirect_stderr(self.output):
                result = runpy.run_path(str(RELOAD_SCRIPT), run_name="__main__",
                                        init_globals={
                                            "comp": self.comp,
                                            "fusion": self.fusion,
                                        })
            self.loaded_paths = list(sys.path)
        return result

    def test_api_and_dependency_load_when_on_search_path(self):
        (self.lib / "context_dependency.py").write_text(
            "CONTEXT = {'project_name': 'Test Project'}\n", encoding="utf-8")
        (self.scripts / "gazu_api.py").write_text(
            "from context_dependency import CONTEXT\n"
            "def get_context_data():\n"
            "    return True, CONTEXT\n", encoding="utf-8")

        self.run_reload()

        self.comp.SetData.assert_any_call(
            "Gazu.Context", {"project_name": "Test Project"})
        self.comp.SetData.assert_any_call("Gazu.api_error_msg", "")
        self.fusion.RunScript.assert_called_once_with(
            "Scripts:Comp/Gazu/Context/Show.py")

    def test_missing_dependency_preserves_actual_error_and_cached_context(self):
        (self.scripts / "gazu_api.py").write_text(
            "import gazu_missing_dependency_for_test\n", encoding="utf-8")

        self.run_reload()

        error = self.comp.SetData.call_args.args[1]
        self.assertIn("ModuleNotFoundError", error)
        self.assertIn("gazu_missing_dependency_for_test", error)
        self.assertIn("Traceback", self.output.getvalue())
        self.assertIn("sys.path:", self.output.getvalue())
        self.assertEqual(self.comp.SetData.call_count, 1)
        self.fusion.RunScript.assert_called_once()

    def test_missing_api_reports_module_name(self):
        self.run_reload(on_path=False)

        error = self.comp.SetData.call_args.args[1]
        self.assertIn("No module named 'gazu_api'", error)
        self.fusion.RunScript.assert_called_once()

    def test_api_failure_keeps_existing_error_behavior(self):
        (self.scripts / "gazu_api.py").write_text(
            "def get_context_data():\n"
            "    return False, 'Authentication failed'\n", encoding="utf-8")

        self.run_reload()

        self.comp.SetData.assert_called_once_with(
            "Gazu.api_error_msg", "Authentication failed")
        self.fusion.RunScript.assert_called_once()


if __name__ == "__main__":
    unittest.main()
