"""Evidence adversaries: never equate absent tests, retries or stale bytes with success."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from hepta_artifact_qualification import (
    FAMILIES, GATES, PACKAGE, canonical, execution_evidence, gate_success,
    run_gate, source_binding,
)


def fixtures():
    names = [f"{family}::tests::case" for family in FAMILIES]
    inventory = {"test-count": len(names), "rust-suites": {
        PACKAGE: {"package-name": PACKAGE, "status": "listed",
                  "testcases": {name: {"ignored": False} for name in names}}
    }}
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", {"tests": str(len(names))})
    for name in names:
        ET.SubElement(suite, "testcase", {"name": name})
    return inventory, root


class EvidenceTests(unittest.TestCase):
    def test_complete_execution(self):
        inventory, root = fixtures()
        result = execution_evidence(inventory, ET.tostring(root))
        self.assertEqual(result["passed"], len(FAMILIES))
        self.assertEqual(set(result["families"]), set(FAMILIES))

    def test_absent_duplicate_and_extra_cases(self):
        for mutation in ("remove", "duplicate", "extra"):
            with self.subTest(mutation=mutation):
                inventory, root = fixtures()
                suite = root[0]
                if mutation == "remove":
                    suite.remove(suite[0])
                elif mutation == "duplicate":
                    suite.append(copy.deepcopy(suite[0]))
                else:
                    ET.SubElement(suite, "testcase", {"name": "forged"})
                with self.assertRaises(ValueError):
                    execution_evidence(inventory, ET.tostring(root))

    def test_nonpass_outcomes(self):
        for tag in ("failure", "error", "skipped", "flakyFailure", "rerunFailure", "unknown"):
            with self.subTest(tag=tag):
                inventory, root = fixtures()
                ET.SubElement(root[0][0], tag)
                with self.assertRaises(ValueError):
                    execution_evidence(inventory, ET.tostring(root))

    def test_missing_family_even_when_inventory_matches(self):
        inventory, root = fixtures()
        del inventory["rust-suites"][PACKAGE]["testcases"][root[0][0].get("name")]
        inventory["test-count"] -= 1
        root[0].remove(root[0][0])
        with self.assertRaises(ValueError):
            execution_evidence(inventory, ET.tostring(root))

    def test_empty_wrong_package_unlisted_count_drift(self):
        for mutation in ("empty", "package", "unlisted", "count"):
            with self.subTest(mutation=mutation):
                inventory, root = fixtures()
                suite = inventory["rust-suites"][PACKAGE]
                if mutation == "empty":
                    suite["testcases"] = {}
                    inventory["test-count"] = 0
                elif mutation == "package":
                    suite["package-name"] = "another-crate"
                elif mutation == "unlisted":
                    suite["status"] = "skipped"
                else:
                    inventory["test-count"] += 1
                with self.assertRaises(ValueError):
                    execution_evidence(inventory, ET.tostring(root))

    def test_reject_dtd_and_summary_failure(self):
        inventory, root = fixtures()
        with self.assertRaises(ValueError):
            execution_evidence(inventory, b'<!DOCTYPE testsuites><testsuites/>')
        root[0].set("failures", "1")
        with self.assertRaises(ValueError):
            execution_evidence(inventory, ET.tostring(root))

    def test_gate_set_and_status_are_closed(self):
        good = {name: {"status": "completed", "exitCode": 0} for name in GATES}
        self.assertTrue(gate_success(good))
        for status, code in (("skipped", 0), ("not_started", 0), ("completed", 1), ("completed", False)):
            with self.subTest(status=status, code=code):
                bad = copy.deepcopy(good)
                bad["tests"] = {"status": status, "exitCode": code}
                self.assertFalse(gate_success(bad))
        bad = copy.deepcopy(good)
        del bad["build"]
        self.assertFalse(gate_success(bad))

    def test_canonical_key_order(self):
        self.assertEqual(canonical({"b": 1, "a": 2}), canonical({"a": 2, "b": 1}))

    def test_gate_failure_does_not_prevent_next_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            failed = run_gate(root, root, "bad", [sys.executable, "-c", "raise SystemExit(7)"], 3)
            passed = run_gate(root, root, "good", [sys.executable, "-c", "print('executed')"], 3)
            self.assertEqual((failed["exitCode"], passed["exitCode"]), (7, 0))
            self.assertEqual((root / "good.stdout").read_text(), "executed\n")

    def test_timeout_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_gate(root, root, "timeout", [sys.executable, "-c", "import time; time.sleep(20)"], 1)
            self.assertEqual((result["status"], result["exitCode"]), ("timed_out", 124))

    def test_existing_gate_output_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test.stdout").write_text("old")
            with self.assertRaises(FileExistsError):
                run_gate(root, root, "test", [sys.executable, "-c", "pass"], 3)

    def test_source_identity_and_seals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
            git("init", "-q")
            git("config", "user.email", "fixture@example.invalid")
            git("config", "user.name", "Fixture")
            paths = ("docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json",
                     "scripts/hepta_artifact_qualification.py",
                     ".github/workflows/hepta-learning-artifacts-qualification.yml",
                     "codex-rs/Cargo.lock", "codex-rs/.config/nextest.toml", "justfile")
            for path in paths:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("fixture\n")
            (root / paths[0]).write_text(json.dumps({"sourceObjects": [], "operations": []}))
            git("add", ".")
            git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            git("commit", "--allow-empty", "-qm", "source")
            source = git("rev-parse", "HEAD")
            value = source_binding(root, source, base, "exact-head")
            self.assertEqual(value["testedCommit"], source)
            for wrong_source, wrong_lane in ((base, "exact-head"), (source, "synthetic-merge")):
                with self.assertRaises(ValueError):
                    source_binding(root, wrong_source, base, wrong_lane)
            (root / "justfile").write_text("dirty")
            with self.assertRaises(ValueError):
                source_binding(root, source, base, "exact-head")


if __name__ == "__main__":
    unittest.main()
