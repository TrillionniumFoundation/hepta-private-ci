import importlib.util
from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("qualification", Path(__file__).with_name("hepta_inference_worker_qualification.py"))
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)


class QualificationTests(unittest.TestCase):
    def test_junit_does_not_trust_empty_or_success_attributes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xml"
            for text in ["<testsuite tests='20'/>", "<testsuites/>"]:
                path.write_text(text)
                self.assertNotEqual(qualification.junit_result(path)["result"], "passed")

    def test_missing_invalid_or_entity_report_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xml"
            self.assertNotEqual(qualification.junit_result(path)["result"], "passed")
            for text in ["bad XML", "<!DOCTYPE x><testsuite><testcase/></testsuite>"]:
                path.write_text(text)
                self.assertNotEqual(qualification.junit_result(path)["result"], "passed")

    def test_real_testcase_pass_and_failure_skip_setup_error_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xml"
            for inner in ["<failure/>", "<error/>", "<skipped/>"]:
                path.write_text(f"<testsuite><testcase>{inner}</testcase></testsuite>")
                self.assertNotEqual(qualification.junit_result(path)["result"], "passed")
            path.write_text("<testsuite errors='1'><testcase/></testsuite>")
            self.assertNotEqual(qualification.junit_result(path)["result"], "passed")
            path.write_text("<testsuite><testcase name='actual'/></testsuite>")
            self.assertEqual(qualification.junit_result(path)["result"], "passed")

    def test_commands_separate_owners_and_experimental_features(self):
        for package in qualification.PACKAGES:
            stages = dict(qualification.stage_commands(package))
            self.assertEqual(set(stages), {"lib", "binary", "all_targets", "clippy"})
            for command in stages.values():
                self.assertEqual(command.count("-p"), 1)
                self.assertIn(package, command)
                self.assertNotIn("--features", command)
            self.assertIn("0", stages["lib"])
            self.assertEqual(stages["clippy"][-2:], ["-D", "warnings"])
        for _, command in qualification.stage_commands(qualification.PACKAGES[1], True):
            self.assertIn("experimental-local-worker", command)

    def test_process_failure_and_timeout_are_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failed = qualification.run_command([sys.executable, "-c", "raise SystemExit(7)"], root, root / "fail.log", 3, dict(os.environ))
            self.assertEqual(failed["result"], "failed")
            timed = qualification.run_command([sys.executable, "-c", "import time; time.sleep(30)"], root, root / "timeout.log", 1, dict(os.environ))
            self.assertEqual(timed["result"], "timed_out")
            passed = qualification.run_command([sys.executable, "-c", "print('ok')"], root, root / "pass.log", 3, dict(os.environ))
            self.assertEqual(passed["result"], "passed")

    def test_exact_source_and_merge_are_bound_and_dirty_tree_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
            git("init", "-q")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.invalid")
            (root / "file").write_text("base\n")
            git("add", ".")
            git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            (root / "file").write_text("source\n")
            git("commit", "-qam", "source")
            source = git("rev-parse", "HEAD")
            self.assertIsNone(qualification.candidate_error(root, source, source, base, "source-head"))
            self.assertIsNone(qualification.candidate_error(root, source, source, base, "merge-candidate"))
            self.assertIsNotNone(qualification.candidate_error(root, base, source, base, "source-head"))
            self.assertIsNotNone(qualification.candidate_error(root, source, source, "", "merge-candidate"))
            (root / "file").write_text("dirty\n")
            self.assertIsNotNone(qualification.candidate_error(root, source, source, base, "source-head"))

    def test_stale_junit_is_removed_before_real_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
            git("init", "-q")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.invalid")
            (root / "file").write_text("source\n")
            git("add", ".")
            git("commit", "-qm", "source")
            sha = git("rev-parse", "HEAD")
            report = root / "codex-rs/target/nextest/default/junit.xml"
            report.parent.mkdir(parents=True)
            report.write_text("<testsuite><testcase name='old'/></testsuite>")
            output = Path(directory) / "evidence"
            argv = ["qualify", "--root", str(root), "--source-sha", sha,
                    "--tested-sha", sha, "--lane", "source-head", "--output", str(output),
                    "--package", "codex-hepta-infer-worker-host"]
            # Successful process exit with no new report must not reuse the old one.
            with patch.object(sys, "argv", argv), patch.object(qualification, "run_command", side_effect=lambda *args: {"result": "passed", "returncode": 0}), redirect_stdout(StringIO()):
                self.assertEqual(qualification.main(), 1)
            import json
            result = json.loads((output / "CURRENT_STATUS.json").read_text())
            self.assertEqual(result["result"], "failed")
            self.assertEqual(result["real_hardware_result"], "not_executed")
            self.assertEqual(result["independent_acceptance_result"], "not_executed")
            self.assertFalse(result["activation"])
            self.assertTrue(all(value == "failed" for value in result["lib_test_result"].values()))

    def test_atomic_json_is_readable_and_no_temporary_is_left(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "CURRENT_STATUS.json"
            qualification.save(path, {"result": "in_progress", "activation": False})
            import json
            self.assertEqual(json.loads(path.read_text())["result"], "in_progress")
            self.assertFalse(path.with_suffix(".tmp").exists())


if __name__ == "__main__":
    unittest.main()
