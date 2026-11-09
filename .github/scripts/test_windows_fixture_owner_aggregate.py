"""Exercise aggregation rejection controls with synthetic files only."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from hepta_ci_junit import NoDoctypeTreeBuilder
import windows_fixture_owner_aggregate as subject


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.group = {
            "id": "example",
            "binaryId": "example-bin",
            "required": ["case"],
            "prefixes": {},
            "expected": 1,
        }
        self.scope = {
            "groups": [self.group],
            "expectedTotal": 1,
            "explicitSkipMarkers": ["guard skipped original case"],
        }
        self.identity = {
            "source": "a" * 40,
            "tree": "b" * 40,
            "observer": "c" * 40,
            "run": "123",
            "attempt": "1",
        }
        self.keys = [["example-bin", "case"]]
        self.selection = {"selected": self.keys, "excludedCount": 5}
        self.command = {
            "status": "completed",
            "exitCode": 0,
            "startedUnix": time.time() - 60,
            "finishedUnix": time.time() + 60,
            "wallSecondsNotFullCost": 0.1,
        }
        self.xml = b'<testsuites><testsuite><testcase classname="example-bin" name="case"/></testsuite></testsuites>'
        self.result = {
            "scope": self.group,
            "selection": self.selection,
            "discoveryExecution": self.command,
            "nativeExecution": self.command,
            "junit": {"sha256": hashlib.sha256(self.xml).hexdigest()},
            "passed": True,
            "binariesUnchanged": True,
            "explicitSkipMarkers": [],
            "leakObservations": {"terminalLines": [], "nonzeroSummaryCounts": []},
        }
        self.receipt = {
            "sourceSha": self.identity["source"],
            "testedSha": self.identity["source"],
            "sourceTree": self.identity["tree"],
            "observerSha": self.identity["observer"],
            "github": {
                "GITHUB_RUN_ID": "123",
                "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_SHA": self.identity["observer"],
            },
            "selectedGroupId": "example",
            "selectedExpectedTotal": 1,
            "originalExpectedTotal": 1,
            "scope": self.scope,
            "executionTopology": "additional_owner_group_job",
            "originalSingleJobReplayed": False,
            "originalSingleJobResultSuperseded": False,
            "sourceUnchanged": True,
            "groups": [self.result],
            "exitCode": 0,
            "status": "passed_selected_scope",
        }
        self.sources = {
            "source": {
                "head": self.identity["source"],
                "tree": self.identity["tree"],
                "allChanges": "",
            },
            "observer": {"head": self.identity["observer"], "allChanges": ""},
        }
        self.store()

    def put(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())

    def store(self):
        self.put("started.json", self.receipt)
        self.put("RECEIPT.json", self.receipt)
        self.put("source-before.json", self.sources)
        self.put("source-after.json", self.sources)
        self.put("example/selection.json", self.selection)
        self.put("example/discovery.json", self.result["discoveryExecution"])
        self.put("example/tests.json", self.result["nativeExecution"])
        self.put("example/tests.stdout", b"")
        self.put("example/tests.stderr", b"")
        self.put("example/nextest-store/local/junit.xml", self.xml)
        self.manifest()

    def manifest(self):
        entries = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.name == "MANIFEST.json":
                continue
            data = path.read_bytes()
            entries.append(
                {
                    "path": "C:\\original-records\\"
                    + str(path.relative_to(self.root)).replace("/", "\\"),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "st_size": len(data),
                    "st_mtime_ns": path.stat().st_mtime_ns,
                }
            )
        self.put("MANIFEST.json", entries)

    def verify(self):
        return subject.verify_group(
            self.root, self.group, self.scope, self.identity, NoDoctypeTreeBuilder
        )

    def test_complete_fixture_has_exact_unique_case_accounting(self):
        result = self.verify()
        self.assertTrue(result["passed"])
        self.assertTrue(result["cleanPassedClaimed"])
        self.assertEqual(
            (result["executed"], result["xmlPassedCount"], result["failures"]),
            (1, 1, 0),
        )

    def test_wrong_run_source_or_group_does_not_pass(self):
        for field, value in (
            ("sourceSha", "d" * 40),
            ("selectedGroupId", "another"),
            ("originalSingleJobReplayed", True),
        ):
            with self.subTest(field=field):
                original = self.receipt[field]
                self.receipt[field] = value
                self.store()
                with self.assertRaises(ValueError):
                    self.verify()
                self.receipt[field] = original
        self.receipt["github"]["GITHUB_RUN_ID"] = "old-run"
        self.store()
        with self.assertRaises(ValueError):
            self.verify()

    def test_missing_or_changed_original_member_is_rejected(self):
        path = self.root / "example/tests.stderr"
        path.write_bytes(b"changed after original capture")
        with self.assertRaises(ValueError):
            self.verify()
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.verify()

    def test_intermediate_source_drift_cannot_be_restored_away(self):
        changed = copy.deepcopy(self.sources)
        changed["source"]["allChanges"] = " M source.rs"
        self.put("example-after-source.json", changed)
        self.manifest()
        with self.assertRaises(ValueError):
            self.verify()

    def test_failed_original_case_keeps_actual_counts_and_stays_failed(self):
        self.xml = self.xml.replace(b"/>", b"><failure/></testcase>")
        self.result["junit"]["sha256"] = hashlib.sha256(self.xml).hexdigest()
        self.result["nativeExecution"] = {**self.command, "exitCode": 1}
        self.result["passed"] = False
        self.receipt.update(exitCode=1, status="failed_or_incomplete")
        self.store()
        result = self.verify()
        self.assertFalse(result["passed"])
        self.assertEqual(
            (result["executed"], result["xmlPassedCount"], result["failures"]),
            (1, 0, 1),
        )

    def test_wrong_junit_key_or_stale_original_timestamp_is_rejected(self):
        self.xml = self.xml.replace(b'name="case"', b'name="different"')
        self.result["junit"]["sha256"] = hashlib.sha256(self.xml).hexdigest()
        self.store()
        with self.assertRaises(ValueError):
            self.verify()
        self.xml = self.xml.replace(b'name="different"', b'name="case"')
        self.result["junit"]["sha256"] = hashlib.sha256(self.xml).hexdigest()
        self.store()
        entries = subject.read_json(self.root / "MANIFEST.json")
        for entry in entries:
            if entry["path"].endswith("junit.xml"):
                entry["st_mtime_ns"] = 1
        self.put("MANIFEST.json", entries)
        with self.assertRaises(ValueError):
            self.verify()

    def test_passed_junit_cannot_rescue_guard_skip_or_leak(self):
        for log in (
            b"guard skipped original case",
            b"LEAK [ 1s] example-bin case\n1 passed (1 leaky)",
        ):
            with self.subTest(log=log):
                self.put("example/tests.stderr", log)
                self.manifest()
                result = self.verify()
                self.assertFalse(result["passed"])
                self.assertFalse(result["cleanPassedClaimed"])
                self.assertEqual(result["xmlPassedCount"], 1)
                self.assertIn("XML only", result["passCountSemantics"])
                self.assertEqual(result["leakObserved"], log.startswith(b"LEAK"))

    def test_missing_prefix_case_and_extra_case_are_both_rejected(self):
        group = {
            "binaryId": "binary",
            "required": [],
            "prefixes": {"parameter::": 4},
            "expected": 4,
        }
        keys = [["binary", f"parameter::{n}"] for n in range(4)]
        self.assertTrue(subject.expected_selection(keys, group))
        self.assertFalse(subject.expected_selection(keys[:3], group))
        self.assertFalse(
            subject.expected_selection(keys + [["binary", "parameter::4"]], group)
        )


if __name__ == "__main__":
    unittest.main()
