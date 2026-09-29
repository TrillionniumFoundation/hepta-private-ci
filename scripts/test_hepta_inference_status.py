"""Status receipts cannot turn missing, skipped, or zero-test runs green."""
import tempfile
from pathlib import Path
import unittest

from scripts.hepta_inference_status import REQUIRED, read_junit, summarize


class ReceiptTests(unittest.TestCase):
    def test_missing_and_non_success_steps_block(self):
        good = {name: {"outcome": "success"} for name in REQUIRED}
        self.assertTrue(summarize(good)[1])
        for name in REQUIRED:
            for outcome in ("skipped", "failure", "cancelled", "neutral", True, {}):
                with self.subTest(name=name, outcome=outcome):
                    self.assertFalse(summarize({**good, name: {"outcome": outcome}})[1])
            incomplete = dict(good)
            incomplete.pop(name)
            self.assertFalse(summarize(incomplete)[1])

    def test_junit_requires_real_non_skipped_successful_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(read_junit(root)[1])
            for name in ("infer_core", "worker", "agentd"):
                (root / f"{name}.xml").write_text('<testsuites><testsuite><testcase name="observed"/></testsuite></testsuites>')
            self.assertTrue(read_junit(root)[1])
            for invalid in (
                '<testsuites/>',
                '<testsuite><testcase><skipped/></testcase></testsuite>',
                '<testsuite><testcase><failure/></testcase></testsuite>',
                '<testsuite><error/><testcase/></testsuite>',
                'not xml',
            ):
                (root / "worker.xml").write_text(invalid)
                self.assertFalse(read_junit(root)[1])

    def test_failed_nextest_report_retains_executed_cases_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("infer_core", "worker", "agentd"):
                (root / f"{name}.xml").write_text(
                    '<testsuites tests="2" failures="1" errors="0">'
                    '<testsuite tests="2" failures="1" disabled="0">'
                    '<testcase name="passed"/>'
                    '<testcase name="failed"><failure>diagnostic</failure></testcase>'
                    '</testsuite></testsuites>'
                )
            evidence, passed = read_junit(root)
            self.assertFalse(passed)
            self.assertEqual(evidence["worker"]["status"], "failed")
            self.assertEqual(evidence["worker"]["tests"], 2)
            self.assertEqual(evidence["worker"]["failures"], 1)
            self.assertEqual(evidence["worker"]["failing_cases"], ["failed"])
            self.assertEqual(len(evidence["worker"]["sha256"]), 64)

    def test_counter_drift_and_entity_expansion_cannot_become_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("infer_core", "worker", "agentd"):
                (root / f"{name}.xml").write_text('<testsuite tests="1"><testcase/></testsuite>')
            for raw in (
                '<testsuite tests="48"><testcase/></testsuite>',
                '<testsuite failures="-1"><testcase/></testsuite>',
                '<testsuite disabled="1"><testcase/></testsuite>',
                '<!DOCTYPE a [<!ENTITY x "expanded">]><testsuite><testcase>&x;</testcase></testsuite>',
                '<unexpected><testcase/></unexpected>',
            ):
                with self.subTest(raw=raw):
                    (root / "worker.xml").write_text(raw)
                    self.assertFalse(read_junit(root)[1])


class CandidateIntegrationTests(unittest.TestCase):
    """Exercise real Git identity/dirty-tree checks using synthetic JUnit fixtures.

    These are tests of the receipt generator, not Rust or provider qualification.
    """

    def setUp(self):
        import shutil
        import subprocess
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        (self.root / "scripts").mkdir()
        source = Path(__file__).with_name("hepta_inference_status.py")
        shutil.copy2(source, self.root / "scripts" / source.name)
        self.git = lambda *args: subprocess.check_output(
            ["git", "-C", str(self.root), *args], text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Receipt unit test")
        self.git("config", "user.email", "receipt-test@example.invalid")
        self.git("add", ".")
        self.git("commit", "-m", "fixture base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-b", "candidate")
        (self.root / "source-only.txt").write_text("candidate bytes\n")
        self.git("add", ".")
        self.git("commit", "-m", "fixture candidate")
        self.source = self.git("rev-parse", "HEAD")
        self.evidence = Path(self.temp.name) / "evidence"
        self.evidence.mkdir()
        for name in ("infer_core", "worker", "agentd"):
            (self.evidence / f"{name}.xml").write_text(
                '<testsuites><testsuite><testcase name="synthetic receipt fixture"/></testsuite></testsuites>'
            )

    def receipt(self, lane="source-head", source=None, base=None):
        import json
        import os
        import subprocess
        import sys
        output = self.evidence / "CURRENT_STATUS.json"
        env = {
            **os.environ,
            "SOURCE_SHA": source or self.source,
            "BASE_SHA": base or self.base,
            "LANE": lane,
            "RUNNER_OS": "Linux",
            "GITHUB_RUN_ID": "fixture-run-not-a-real-CI-receipt",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_JOB": "receipt-unit-test",
            "STEP_RESULTS": json.dumps({name: {"outcome": "success"} for name in REQUIRED}),
        }
        result = subprocess.run(
            [sys.executable, str(self.root / "scripts/hepta_inference_status.py"),
             "--output", str(output), "--junit-dir", str(self.evidence)],
            env=env, capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertTrue(output.is_file(), result.stderr)
        return result.returncode, json.loads(output.read_text())

    def test_source_receipt_binds_actual_git_blobs_without_claiming_other_os(self):
        code, record = self.receipt()
        self.assertEqual(code, 0)
        self.assertEqual(record["source_head"], self.source)
        self.assertEqual(record["source_blob_digests"]["source-only.txt"]["git_blob"],
                         self.git("rev-parse", f"{self.source}:source-only.txt"))
        self.assertEqual(record["macos_result"], "not_observed")
        self.assertIsNone(record["last_merge_candidate_run"])
        self.assertFalse(record["activation"])
        self.assertEqual(record["real_hardware_result"], "not_observed")

    def test_wrong_source_and_dirty_tree_cannot_pass(self):
        code, record = self.receipt(source=self.base)
        self.assertNotEqual(code, 0)
        self.assertFalse(record["candidate_identity_verified"])
        (self.root / "source-only.txt").write_text("uncommitted drift\n")
        code, record = self.receipt()
        self.assertNotEqual(code, 0)
        self.assertFalse(record["tracked_tree_clean"])

    def test_merge_candidate_binds_source_separately_from_tested_tree(self):
        self.git("checkout", "main")
        (self.root / "base-only.txt").write_text("new base\n")
        self.git("add", ".")
        self.git("commit", "-m", "fixture updated base")
        new_base = self.git("rev-parse", "HEAD")
        self.git("checkout", "candidate")
        code, record = self.receipt(lane="merge-candidate", base=new_base)
        self.assertNotEqual(code, 0)
        self.assertFalse(record["candidate_identity_verified"])
        self.git("merge", "--no-ff", new_base, "-m", "fixture synthetic merge")
        code, record = self.receipt(lane="merge-candidate", base=new_base)
        self.assertEqual(code, 0)
        self.assertNotEqual(record["source_tree"], record["tested_tree"])
        self.assertNotIn("base-only.txt", record["source_blob_digests"])
        self.assertIsNone(record["last_exact_head_run"])
        self.assertIsNotNone(record["last_merge_candidate_run"])


if __name__ == "__main__":
    unittest.main()
