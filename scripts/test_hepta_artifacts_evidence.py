"""Negative evidence tests use synthetic receipts, not claimed Rust execution."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import hepta_artifacts_evidence as evidence


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = "a" * 40
        self.base = "b" * 40
        self.log = "test tests::identity ... ok\n\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n"

    def receipt(self, lane="source"):
        directory = self.root / lane
        directory.mkdir(exist_ok=True)
        commands = {}
        for name in evidence.REQUIRED:
            data = self.log.encode() if name == "tests" else b'{"ok":true,"findings":[]}\n'
            (directory / (name + ".log")).write_bytes(data)
            commands[name] = {"argv": evidence.COMMANDS[name], "exitCode": 0, "timedOut": False,
                              "logLimitExceeded": False, "log": name + ".log",
                              "logSha256": evidence.digest(data), "logBytes": len(data)}
        value = {"schema": evidence.SCHEMA, "qualified": True, "problems": [],
                 "sourceCommit": self.source, "baseCommit": self.base,
                 "candidateCommit": self.source if lane == "source" else "c" * 40,
                 "candidateTree": "d" * 40, "parents": [self.base, self.source],
                 "runId": "1", "runAttempt": "1", "job": "qualification", "lane": lane,
                 "commands": commands, "tests": evidence.assess_test_output(self.log),
                 "sourceBlobs": {"test.rs": "e" * 40},
                 "traceability": [{"requirement": f"ART-{i:02d}", "source": "test.rs", "blob": "e" * 40,
                                   "executedTest": "tests::identity", "command": "tests"} for i in range(1, 13)],
                 "claimBoundary": {name: False for name in evidence.DENIED}}
        path = directory / "qualification.json"
        path.write_bytes(evidence.canonical(value))
        return path, value

    def verify(self, path):
        return evidence.verify_receipt(path, self.source, self.base, "1", "1")

    def test_valid_synthetic_receipt(self):
        path, value = self.receipt()
        self.assertEqual(self.verify(path), value)

    def test_zero_tests_rejected(self):
        with self.assertRaisesRegex(ValueError, "zero"):
            evidence.assess_test_output("test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out")

    def test_ignored_tests_rejected(self):
        with self.assertRaises(ValueError):
            evidence.assess_test_output(self.log.replace("... ok", "... ignored"))

    def test_failed_tests_rejected(self):
        with self.assertRaises(ValueError):
            evidence.assess_test_output(self.log.replace("... ok", "... FAILED"))

    def test_filtered_tests_rejected(self):
        with self.assertRaises(ValueError):
            evidence.assess_test_output(self.log.replace("0 filtered", "1 filtered"))

    def test_duplicate_test_identity_rejected(self):
        with self.assertRaises(ValueError):
            evidence.assess_test_output("test tests::identity ... ok\n" + self.log)

    def test_missing_terminal_summary_rejected(self):
        with self.assertRaises(ValueError):
            evidence.assess_test_output("test tests::identity ... ok\n")

    def test_summary_count_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            evidence.assess_test_output(self.log.replace("1 passed", "2 passed"))

    def test_receipt_mutations_rejected(self):
        path, value = self.receipt()
        mutations = [
            ("qualified", False), ("problems", ["failure"]), ("sourceCommit", "f" * 40),
            ("baseCommit", "f" * 40), ("runId", "2"), ("runAttempt", "2"),
            ("lane", "unknown"), ("candidateCommit", "f" * 40), ("candidateTree", "short"),
            ("traceability", []), ("sourceBlobs", {}),
        ]
        for field, changed in mutations:
            with self.subTest(field=field):
                candidate = copy.deepcopy(value)
                candidate[field] = changed
                path.write_bytes(evidence.canonical(candidate))
                with self.assertRaises(ValueError):
                    self.verify(path)

    def test_authority_escalation_rejected(self):
        path, value = self.receipt()
        for name in evidence.DENIED:
            candidate = copy.deepcopy(value)
            candidate["claimBoundary"][name] = True
            path.write_bytes(evidence.canonical(candidate))
            with self.assertRaises(ValueError):
                self.verify(path)

    def test_command_substitution_rejected(self):
        path, value = self.receipt()
        value["commands"]["tests"]["argv"] = ["true"]
        path.write_bytes(evidence.canonical(value))
        with self.assertRaisesRegex(ValueError, "substitution"):
            self.verify(path)

    def test_failed_timeout_or_limited_command_rejected(self):
        path, value = self.receipt()
        for field, changed in (("exitCode", 1), ("exitCode", False), ("timedOut", True), ("logLimitExceeded", True)):
            candidate = copy.deepcopy(value)
            candidate["commands"]["build"][field] = changed
            path.write_bytes(evidence.canonical(candidate))
            with self.assertRaises(ValueError):
                self.verify(path)

    def test_log_tampering_rejected(self):
        path, _ = self.receipt()
        (path.parent / "build.log").write_text("changed")
        with self.assertRaisesRegex(ValueError, "binding"):
            self.verify(path)

    def test_log_path_escape_rejected(self):
        path, value = self.receipt()
        value["commands"]["tests"]["log"] = "../tests.log"
        path.write_bytes(evidence.canonical(value))
        with self.assertRaisesRegex(ValueError, "unsafe"):
            self.verify(path)

    def test_two_lanes_required(self):
        self.receipt()
        with self.assertRaises(ValueError):
            evidence.aggregate(self.root, self.source, self.base, "1", "1", {"qualification": {"result": "success"}})
        self.receipt("merge")
        evidence.aggregate(self.root, self.source, self.base, "1", "1", {"qualification": {"result": "success"}})

    def test_skipped_failed_or_missing_job_rejected(self):
        self.receipt()
        self.receipt("merge")
        for result in ("skipped", "failure", "cancelled", "neutral", "pending"):
            with self.assertRaises(ValueError):
                evidence.aggregate(self.root, self.source, self.base, "1", "1", {"qualification": {"result": result}})
        with self.assertRaises(ValueError):
            evidence.aggregate(self.root, self.source, self.base, "1", "1", {})

    def test_reversed_merge_parents_rejected(self):
        path, value = self.receipt("merge")
        value["parents"].reverse()
        path.write_bytes(evidence.canonical(value))
        with self.assertRaises(ValueError):
            self.verify(path)

    def test_actual_git_blob_and_dirty_identity(self):
        root = self.root / "repo"
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        source = root / "codex-rs/hepta-learning-artifacts/src/lib.rs"
        source.parent.mkdir(parents=True)
        source.write_text("// fixture\n")
        evidence.git(root, "add", ".")
        evidence.git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
        head = evidence.git(root, "rev-parse", "HEAD")
        identity = evidence.identity(root, head, head, "source")
        self.assertEqual(len(identity["sourceBlobs"]), 1)
        source.write_text("// modified\n")
        with self.assertRaisesRegex(ValueError, "dirty"):
            evidence.identity(root, head, head, "source")

    def test_timeout_is_negative_evidence(self):
        result = evidence.execute([os.sys.executable, "-c", "import time; time.sleep(10)"], self.root, self.root / "timeout.log", timeout=0)
        self.assertTrue(result["timedOut"])
        self.assertNotEqual(result["exitCode"], 0)


if __name__ == "__main__":
    unittest.main()
