"""Run the REAL CLI in subprocesses, without inherited PYTHONPATH or models."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/memory_cell/shared_question_gate_trial.py"


class EntryPointTests(unittest.TestCase):
    def run_cli(self, arguments, cwd):
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1")
        return subprocess.run([sys.executable, str(SCRIPT), *arguments], cwd=cwd, env=env,
                              text=True, capture_output=True, timeout=40)

    def test_absolute_cli_help_from_foreign_directory(self):
        with tempfile.TemporaryDirectory() as d:
            result = self.run_cli(["--help"], d)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--original-archive", result.stdout)
            self.assertIn("--select-archive", result.stdout)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_repo_root_cli_help_matches_foreign_directory(self):
        at_root = self.run_cli(["--help"], ROOT)
        with tempfile.TemporaryDirectory() as d:
            elsewhere = self.run_cli(["--help"], d)
        self.assertEqual(at_root.returncode, 0, at_root.stderr)
        self.assertEqual(elsewhere.returncode, 0, elsewhere.stderr)
        self.assertEqual(at_root.stdout, elsewhere.stdout)

    def test_missing_arguments_reach_argparse_not_import_failure(self):
        with tempfile.TemporaryDirectory() as d:
            result = self.run_cli([], d)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("required", result.stderr)
            self.assertNotIn("ModuleNotFoundError", result.stderr)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_working_directory_cannot_supply_the_execution_module(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "experiments.py").write_text("raise RuntimeError('wrong directory module')\n")
            result = self.run_cli(["--help"], d)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("wrong directory module", result.stderr)


if __name__ == "__main__":
    unittest.main()
