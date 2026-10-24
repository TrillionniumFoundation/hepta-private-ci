"""Run with a project runtime containing pytest; no new dependency installation."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from prospective_action_observer import classify


class ProspectiveObserverTests(unittest.TestCase):
    def test_uncaught_import_is_unavailable_even_in_call_phase(self):
        for exception in ("ImportError", "ModuleNotFoundError"):
            value = classify([{"phase": "call", "status": "failed", "exception": exception}], 1)
            self.assertEqual(value["outcome"], "infrastructure_error")
        self.assertEqual(classify([{"phase": "call", "status": "failed", "exception": "AssertionError"}], 1)["outcome"], "test_failure")

    def test_both_real_frameworks_preserve_lazy_import_and_caught_import_semantics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test_lazy.py").write_text('''import unittest
class Checks(unittest.TestCase):
    def test_missing(self):
        import hepta_nonexistent_fixture_dependency_20261024
    def test_expected(self):
        with self.assertRaises(ImportError):
            import hepta_nonexistent_fixture_dependency_20261024
    def test_subclass(self):
        class MissingPlugin(ImportError):
            pass
        raise MissingPlugin("uncaught dependency subclass")
    def test_resource(self):
        raise PermissionError(1, "fixture sandbox denial")
''')
            observer = Path(__file__).with_name("prospective_action_observer.py").resolve()
            for runner in ("unittest", "pytest"):
                for method, expected in (("test_missing", "infrastructure_error"), ("test_expected", "pass"),
                                         ("test_subclass", "infrastructure_error"), ("test_resource", "infrastructure_error")):
                    result = root / (runner + "-" + method + ".json")
                    selector = ("test_lazy.Checks." + method if runner == "unittest"
                                else str(root / "test_lazy.py") + "::Checks::" + method)
                    args = [selector] if runner == "unittest" else ["--assert=plain", "-q", selector]
                    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPYCACHEPREFIX=str(root / "private-cache"),
                               PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
                    child = subprocess.run([sys.executable, str(observer), "--runner", runner,
                        "--output", str(result), "--", *args], cwd=root, env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
                    data = json.loads(result.read_bytes())
                    self.assertEqual(data["outcome"], expected, (runner, data, child.stderr.decode()))
                    self.assertEqual(data["uncaught_import_failures"], int(method in ("test_missing", "test_subclass")))
                    self.assertEqual(data["uncaught_resource_failures"], int(method == "test_resource"))


if __name__ == "__main__":
    unittest.main()
