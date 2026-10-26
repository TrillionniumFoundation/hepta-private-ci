"""The observation must restore original source even when native data is absent."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("prepare_windows_delete_probe.py")
SPEC = importlib.util.spec_from_file_location("delete_probe_runner", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ObservationRestorationTests(unittest.TestCase):
    def test_missing_native_log_fails_and_restores_every_original_assertion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in MODULE.EXPECTED:
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text((MODULE.ROOT / name).read_text(), newline="\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "core.autocrlf", "false"], cwd=root, check=True
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=CI Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "-q",
                    "-m",
                    "Original source fixture",
                ],
                cwd=root,
                check=True,
            )
            output = root / "evidence"
            output.mkdir()
            original = (root / MODULE.PATH).read_bytes()
            with patch.object(MODULE, "ROOT", root):
                MODULE.prepare(output)
                self.assertIn("delete_probe::record", (root / MODULE.PATH).read_text())
                self.assertIn("assert_eq!(refused,", (root / MODULE.PATH).read_text())
                with self.assertRaises(FileNotFoundError):
                    MODULE.collect(output)
                self.assertEqual((root / MODULE.PATH).read_bytes(), original)
                self.assertEqual(MODULE.source()["trackedChanges"], "")


if __name__ == "__main__":
    unittest.main()
