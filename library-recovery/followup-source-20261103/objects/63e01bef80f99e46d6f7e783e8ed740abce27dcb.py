"""Test that the local acceptance runner cannot manufacture a closure claim."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_hepta_local_closeout as mod


class LocalCloseoutTests(unittest.TestCase):
    def test_unmounted_checkout_is_not_a_source(self):
        with tempfile.TemporaryDirectory() as root:
            result = mod.git_snapshot(Path(root) / "not-mount")
            self.assertFalse(result["usable"])
            self.assertNotIn("commit", result)

    def test_real_local_git_source_identity(self):
        with tempfile.TemporaryDirectory() as root:
            src = Path(root)
            subprocess.run(["git", "init", "-q", str(src)], check=True)
            subprocess.run(["git", "-C", str(src), "-c", "user.name=LocalTest", "-c", "user.email=local@example.invalid",
                            "commit", "-q", "--allow-empty", "-m", "baseline"], check=True)
            result = mod.git_snapshot(src)
            self.assertTrue(result["usable"])
            self.assertEqual(len(result["commit"]), 40)
            self.assertEqual(len(result["tree"]), 40)
            self.assertTrue(result["clean"])
            (src / "untracked").write_text("x")
            self.assertFalse(mod.git_snapshot(src)["clean"])

    def test_absent_binary_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            r = mod.run_check(["nonexistent-hepta-executor-check-binary-000", "--version"], Path(root), 10, Path(root) / "log")
            self.assertEqual(r["status"], "BLOCKED_TOOL_MISSING")

    def test_passing_check_produces_nonworldwritable_provenance_log(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "test.log"
            r = mod.run_check([sys.executable, "-c", "print('test-only')"], Path(root), 10, p)
            self.assertEqual(r["status"], "PASS_LOCAL")
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertIn("test-only", p.read_text())
            self.assertEqual(len(r["log_sha256"]), 64)

    def test_failing_check_not_relabelled(self):
        with tempfile.TemporaryDirectory() as root:
            r = mod.run_check([sys.executable, "-c", "raise SystemExit(7)"], Path(root), 10, Path(root) / "f.log")
            self.assertEqual(r["status"], "FAIL_LOCAL")
            self.assertEqual(r["exit_code"], 7)

    def test_timed_out_check_stays_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            r = mod.run_check([sys.executable, "-c", "import time; time.sleep(3)"], Path(root), 1, Path(root) / "x.log")
            self.assertEqual(r["status"], "BLOCKED_TIMEOUT")

    def test_missing_repositories_report_every_stage_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            report_path = Path(root) / "results"
            args = ["run", "--hepta", str(Path(root) / "missing1"), "--runtime", str(Path(root) / "missing2"), "--report-dir", str(report_path)]
            with patch.object(sys, "argv", args), contextlib.redirect_stdout(io.StringIO()):
                code = mod.main()
            self.assertEqual(code, 2)
            reports = list(report_path.glob("run-*/acceptance.json"))
            self.assertEqual(len(reports), 1)
            data = json.loads(reports[0].read_text())
            self.assertFalse(data["production_qualified"])
            self.assertEqual(set(data["stages"]), set(mod.STAGES))
            self.assertTrue(all(s["status"].startswith("BLOCKED") for s in data["stages"].values()))

    def test_mounted_clean_sources_but_not_run_are_still_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            roots = {"hepta": base / "hepta", "runtime": base / "runtime"}
            for name, path in roots.items():
                path.mkdir()
                subprocess.run(["git", "init", "-q", str(path)], check=True)
            for stage in mod.STAGES.values():
                for repo, rel in stage["required"]:
                    file = roots[repo] / rel
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.touch()
            for name, path in roots.items():
                subprocess.run(["git", "-C", str(path), "add", "."], check=True)
                subprocess.run(["git", "-C", str(path), "-c", "user.name=LocalTest", "-c", "user.email=local@example.invalid",
                                "commit", "-q", "--allow-empty", "-m", "test"], check=True)
            with patch.object(sys, "argv", ["run", "--hepta", str(roots["hepta"]), "--runtime", str(roots["runtime"]), "--report-dir", str(base / "results")]), contextlib.redirect_stdout(io.StringIO()):
                code = mod.main()
            self.assertEqual(code, 2)
            report = json.loads(next((base / "results").glob("run-*/acceptance.json")).read_text())
            self.assertTrue(all(s["status"] == "BLOCKED_NOT_RUN" for s in report["stages"].values()))
            self.assertFalse(report["production_qualified"])

    def test_all_local_checks_cannot_claim_full_acceptance(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            roots = {"hepta": base / "hepta", "runtime": base / "runtime"}
            for path in roots.values():
                path.mkdir()
                subprocess.run(["git", "init", "-q", str(path)], check=True)
            for stage in mod.STAGES.values():
                for repo, rel in stage["required"]:
                    file = roots[repo] / rel
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.touch()
            for path in roots.values():
                subprocess.run(["git", "-C", str(path), "add", "."], check=True)
                subprocess.run(["git", "-C", str(path), "-c", "user.name=LocalTest", "-c", "user.email=local@example.invalid",
                                "commit", "-q", "--allow-empty", "-m", "test"], check=True)
            with patch.object(mod, "run_check", return_value={"status": "PASS_LOCAL"}), patch.object(
                sys, "argv", ["run", "--hepta", str(roots["hepta"]), "--runtime", str(roots["runtime"]),
                              "--report-dir", str(base / "results"), "--execute-checks"]
            ), contextlib.redirect_stdout(io.StringIO()):
                code = mod.main()
            self.assertEqual(code, 3, "passing local checks must never give a green production exit code")
            report = json.loads(next((base / "results").glob("run-*/acceptance.json")).read_text())
            self.assertFalse(report["production_qualified"])
            self.assertTrue(all(x["status"] == "SOURCE_TESTED_EXTERNAL_EVIDENCE_PENDING" for x in report["stages"].values()))


if __name__ == "__main__":
    unittest.main()
