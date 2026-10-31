"""Behavioral checks of process accounting, failed jobs and create-only evidence."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

from .study import digest, run, save_new


class StudyTests(unittest.TestCase):
    def test_complete_process_failure_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.txt"
            source.write_text("immutable input")
            plan = {
                "repository_root": str(root),
                "frozen_files": [{"path": "input.txt", "sha256": digest(source)}],
                "jobs": [
                    {"id": "work", "argv": [sys.executable, "-c",
                     "x=bytearray(8*1024*1024); print(sum(i*i for i in range(200000)))"]},
                    {"id": "fail", "argv": [sys.executable, "-c", "raise SystemExit(7)"]},
                    {"id": "blocked", "depends": ["fail"],
                     "argv": [sys.executable, "-c", "raise RuntimeError('must not run')"]},
                    {"id": "missing", "argv": [sys.executable, "-c", "pass"],
                     "outputs": ["absent.json"]},
                ],
            }
            save_new(root / "plan.json", plan)
            result = run(root / "plan.json", root / "results")
            work = json.loads((root / "results/receipts/work/whole_process.json").read_text())
            failed = json.loads((root / "results/receipts/fail/whole_process.json").read_text())
            blocked = json.loads((root / "results/receipts/blocked/whole_process.json").read_text())
            missing = json.loads((root / "results/receipts/missing/whole_process.json").read_text())
            self.assertEqual(work["exit_code"], 0)
            self.assertGreater(work["cpu_total_sec"], 0)
            self.assertGreater(work["wall_sec"], 0)
            self.assertGreater(work["peak_rss_kib"], 8 * 1024)
            self.assertEqual(failed["exit_code"], 7)
            self.assertFalse(blocked["executed"])
            self.assertEqual(missing["process_exit_code"], 0)
            self.assertEqual(missing["exit_code"], 123)
            self.assertEqual(missing["missing_outputs"], ["absent.json"])
            self.assertEqual(set(result["failures"]), {"fail", "blocked", "missing"})
            self.assertEqual(digest(root / "plan.json"), digest(root / "results/plan.json"))
            with self.assertRaises(FileExistsError):
                run(root / "plan.json", root / "results")
            source.write_text("modified")
            with self.assertRaises(RuntimeError):
                run(root / "plan.json", root / "another")


if __name__ == "__main__":
    unittest.main()
