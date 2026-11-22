"""Exercise source binding and failures at the cold-process report boundary."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from . import study_launcher as launcher


class StudyLauncherTests(unittest.TestCase):
    def setup_inputs(self, directory):
        root = Path(directory)
        source = Path(launcher.__file__)
        manifest = {
            "files": [
                {
                    "path": "qualification/hcsn_scale/study_launcher.py",
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            ]
        }
        plan = {"arms": ["fixture"], "seeds": [7]}
        paths = [
            root / name for name in ("SOURCE.json", "STREAM.json", "ADAPTATION.json")
        ]
        for path, value in zip(paths, (manifest, plan, plan)):
            launcher.save(path, value)
        return root, paths

    def test_changed_source_prevents_execution_and_output_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root, paths = self.setup_inputs(directory)
            manifest = json.loads(paths[0].read_text())
            manifest["files"][0]["sha256"] = "0" * 64
            launcher.save(paths[0], manifest)
            with patch.object(launcher.subprocess, "run") as execute:
                with self.assertRaisesRegex(RuntimeError, "frozen source changed"):
                    launcher.run(root / "unused.csv", root / "output", *paths)
            execute.assert_not_called()
            self.assertFalse((root / "output").exists())

    def test_child_failure_and_plan_mismatch_are_preserved_without_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            root, paths = self.setup_inputs(directory)

            def child(command, **kwargs):
                destination = Path(command[4])
                destination.mkdir()
                if command[2].endswith("stream_benchmark"):
                    launcher.save(destination / "RESULT.json", {"state": "completed"})
                    launcher.save(
                        destination / "PLAN.json", {"arms": ["different"], "seeds": [7]}
                    )
                    return subprocess.CompletedProcess(command, 0)
                launcher.save(
                    destination / "STUDY.json",
                    {"state": "failed", "plan": json.loads(paths[2].read_text())},
                )
                return subprocess.CompletedProcess(command, 1)

            with patch.object(launcher.subprocess, "run", side_effect=child) as execute:
                result = launcher.run(root / "unused.csv", root / "output", *paths)
            self.assertEqual(execute.call_count, 2)
            self.assertEqual(result["state"], "completed_with_failures")
            by_study = {row["study"]: row for row in result["trials"]}
            self.assertEqual(by_study["stream"]["state"], "plan_mismatch")
            self.assertEqual(by_study["adaptation"]["exit_code"], 1)
            self.assertEqual(
                result, json.loads((root / "output/LAUNCH.json").read_text())
            )
            self.assertTrue(
                all(row["cold_wall_seconds"] >= 0 for row in result["trials"])
            )


if __name__ == "__main__":
    unittest.main()
