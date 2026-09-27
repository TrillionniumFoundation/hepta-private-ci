"""Synthetic negative evidence tests; not artifact-runtime execution evidence."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

import hepta_artifact_qualification as q
import hepta_artifact_receipt_guard as guard


class ReceiptGuardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.out = Path(self.directory.name)
        source_path = q.SOURCE_ROOT + "/src/owner_service.rs"
        self.mapping = {
            "module": "learning.artifacts",
            "operations": [
                {"operation": "publish", "nativeSymbol": "LearningArtifactOwnerService::publish",
                 "sourcePath": source_path, "sourceBlob": "b" * 40,
                 "tests": ["owner_service::tests::case"]},
                {"operation": "unmapped", "nativeSymbol": "pending",
                 "sourcePath": source_path, "sourceBlob": "b" * 40, "tests": []},
            ],
        }
        self.mapping_bytes = q.canonical(self.mapping)
        self.expected = {
            "sourceCommit": "a" * 40, "baseCommit": "c" * 40,
            "testedCommit": "a" * 40, "testedTree": "d" * 40, "lane": "exact-head",
            "runner": {key: "fixture" for key in q.RUNNER_KEYS},
            "sourceObjects": {q.MAP: guard.git_blob(self.mapping_bytes), source_path: "b" * 40},
        }
        names = [f"{family}::tests::case" for family in q.FAMILIES]
        inventory = {"test-count": len(names), "rust-suites": {q.PACKAGE: {
            "package-name": q.PACKAGE, "status": "listed",
            "testcases": {name: {} for name in names},
        }}}
        xml = (f'<testsuites><testsuite name="{q.PACKAGE}">'
               + ''.join(f'<testcase classname="{q.PACKAGE}" name="{name}"/>' for name in names)
               + '</testsuite></testsuites>').encode()
        (self.out / "junit.xml").write_bytes(xml)
        gates = {}
        for name in q.GATES:
            for suffix in ("stdout", "stderr"):
                (self.out / f"{name}.{suffix}").write_bytes(
                    q.canonical(inventory) if (name, suffix) == ("inventory", "stdout") else b""
                )
            gates[name] = {"status": "completed", "exitCode": 0,
                           "stdoutSha256": q.digest(self.out / f"{name}.stdout"),
                           "stderrSha256": q.digest(self.out / f"{name}.stderr")}
        execution = q.execution_evidence(inventory, xml)
        self.receipt = {
            "schema": "hepta.learning-artifacts.qualification.v2", **self.expected,
            "gates": gates, "execution": execution,
            "traceability": q.traceability(self.mapping, execution),
            "errors": [], "qualified": True,
            "completion": {"nativeCandidateQualified": True,
                           "requirementTraceabilityComplete": False, "moduleComplete": False},
            "claimBoundary": {key: False for key in (
                "productionImplementation", "productExecutionProved", "independentAcceptance",
                "activation", "release")},
        }
        self.store()

    def store(self):
        data = q.canonical(self.receipt)
        (self.out / "qualification.json").write_bytes(data)
        (self.out / "qualification.sha256").write_text(hashlib.sha256(data).hexdigest() + "\n")

    def verify(self):
        return guard.verify_bound_bundle(self.out, self.expected, self.mapping_bytes)

    def test_honest_unmapped_obligation_remains_incomplete(self):
        self.assertFalse(self.verify()["completion"]["requirementTraceabilityComplete"])

    def test_rehashed_false_complete_claim_is_rejected(self):
        self.receipt["completion"]["requirementTraceabilityComplete"] = True
        self.store()
        with self.assertRaisesRegex(ValueError, "completion projection"):
            self.verify()

    def test_rehashed_trace_deletion_is_rejected(self):
        self.receipt["traceability"].pop()
        self.store()
        with self.assertRaisesRegex(ValueError, "traceability differs"):
            self.verify()

    def test_rehashed_source_substitution_is_rejected(self):
        self.receipt["traceability"][0]["sourceBlob"] = "f" * 40
        self.store()
        with self.assertRaisesRegex(ValueError, "traceability differs"):
            self.verify()

    def test_receipt_cannot_supply_its_own_new_map(self):
        changed = copy.deepcopy(self.mapping)
        changed["operations"].pop()
        with self.assertRaisesRegex(ValueError, "independently bound Git object"):
            guard.verify_bound_bundle(self.out, self.expected, q.canonical(changed))

    def test_unknown_completion_fields_and_integer_booleans_are_rejected(self):
        for change in ({"productionComplete": True}, {"requirementTraceabilityComplete": 0}):
            original = self.receipt["completion"].copy()
            self.receipt["completion"].update(change)
            self.store()
            with self.assertRaises(ValueError):
                self.verify()
            self.receipt["completion"] = original

    def test_failed_skipped_and_cancelled_gates_are_rejected(self):
        for status in ("skipped", "cancelled", "not_started", "timed_out"):
            self.receipt["gates"]["tests"]["status"] = status
            self.store()
            with self.assertRaises(ValueError):
                self.verify()

    def test_combined_output_budget_precedes_digest_scan(self):
        with (self.out / "build.stdout").open("wb") as file:
            file.truncate(q.MAX_OUTPUT + 1)
        with self.assertRaisesRegex(ValueError, "combined stream budget"):
            self.verify()

    def test_symlinked_evidence_is_rejected(self):
        original = self.out / "build.stdout"
        target = self.out / "target"
        original.rename(target)
        try:
            original.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("host does not support symlink creation")
        with self.assertRaisesRegex(ValueError, "regular file"):
            self.verify()

    def test_duplicate_obligation_is_not_complete_by_vacuity(self):
        self.mapping["operations"].append(copy.deepcopy(self.mapping["operations"][0]))
        self.mapping_bytes = q.canonical(self.mapping)
        self.expected["sourceObjects"][q.MAP] = guard.git_blob(self.mapping_bytes)
        with self.assertRaisesRegex(ValueError, "duplicate mapped obligation"):
            self.verify()

    def test_test_identity_relabel_cannot_be_rehashed_into_success(self):
        self.receipt["traceability"][0]["declaredTests"] = {"owner_service::tests::case": []}
        self.store()
        with self.assertRaisesRegex(ValueError, "traceability differs"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
