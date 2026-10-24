import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from prepare_sanic_trace_condition import launcher_source
from prospective_action_inputs import sha_file


class SanicTraceLauncherTests(unittest.TestCase):
    def test_stack_survives_pytest_fd_capture_and_original_interpreter_is_used(self):
        python = Path(os.environ.get("HEPTA_TRACE_FIXTURE_PYTHON", sys.executable)).absolute()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            test = root/"test_paused.py"
            test.write_text("import time\ndef test_paused():\n    time.sleep(2.0)\n")
            observer = root/"observer.py"
            observer.write_text("import json,sys\nfrom pathlib import Path\nimport pytest\n"
                "original_argv=list(sys.argv)\noriginal_path=sys.path[0]\n"
                "code=pytest.main(['-q','--capture=fd',sys.argv[-1]])\n"
                "Path(sys.argv[sys.argv.index('--output')+1]).write_text(json.dumps({'python':sys.executable,'argv':original_argv,'path0':original_path}))\n"
                "raise SystemExit(code)\n")
            launcher = root/"trace-python"
            launcher.write_text(launcher_source(python, observer, sha_file(observer), delay=1.0))
            launcher.chmod(0o755)
            output = root/"observation.json"
            environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPYCACHEPREFIX=str(root/"fresh-cache"),
                               PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
            result = subprocess.run([str(launcher), str(observer), "--output", str(output), "--", str(test)],
                capture_output=True, env=environment, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            receipt = json.loads(output.read_bytes())
            self.assertEqual(receipt, {"python": str(python), "argv": [str(observer), "--output", str(output), "--", str(test)], "path0": str(root)})
            stack = (root/"stack.log").read_text()
            self.assertIn("test_paused", stack)
            self.assertIn("Timeout", stack)
            self.assertNotIn(b"Timeout", result.stderr)

    def test_lexical_venv_interpreter_is_not_replaced_by_symlink_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            alias = root/"venv-python"
            alias.symlink_to(sys.executable)
            text = launcher_source(alias, root/"observer.py", "a"*64)
            self.assertEqual(text.splitlines()[0], "#!"+str(alias))

    def test_changed_observer_rejected_before_run_or_stack_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observer = root/"observer.py"
            observer.write_text("raise AssertionError('must not execute changed source')\n")
            launcher = root/"trace-python"
            launcher.write_text(launcher_source(sys.executable, observer, "a"*64))
            launcher.chmod(0o755)
            result = subprocess.run([str(launcher), str(observer), "--output", str(root/"observation.json")], capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"original observer changed", result.stderr)
            self.assertFalse((root/"stack.log").exists())


if __name__ == "__main__":
    unittest.main()
