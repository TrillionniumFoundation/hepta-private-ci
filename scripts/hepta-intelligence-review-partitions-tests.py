#!/usr/bin/env python3
"""Reject incomplete or forged review allocations without issuing approval."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).with_name("hepta-intelligence-review-partitions.py")
SPEC = importlib.util.spec_from_file_location("intelligence_review_partitions", PATH)
assert SPEC is not None and SPEC.loader is not None
REVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REVIEW)


class ReviewPartitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.value = REVIEW.FAULT.load_json(REVIEW.DOCS / "REVIEW_PARTITIONS.json")
        self.implementation = REVIEW.FAULT.load_json(
            REVIEW.DOCS / "IMPLEMENTATION_MAP.json"
        )
        self.trace = REVIEW.FAULT.load_json(REVIEW.DOCS / "TEST_TRACEABILITY.json")

    def validate(self, value: dict) -> dict:
        return REVIEW.validate(value, self.implementation, self.trace)

    def reject(self, value: dict) -> None:
        with self.assertRaises(ValueError):
            self.validate(value)

    def test_pending_allocations_cover_all_mapped_sources_and_requirements(
        self,
    ) -> None:
        value = self.validate(self.value)
        self.assertEqual([row["id"] for row in value["partitions"]], list("ABCDEF"))
        self.assertTrue(
            all(row["reviewStatus"] == "pending" for row in value["partitions"])
        )

    def test_wrong_schema_boolean_version_and_unknown_approval_reject(self) -> None:
        for key, value in (
            ("schema", "other"),
            ("schemaVersion", True),
            ("accepted", True),
        ):
            with self.subTest(key=key):
                hostile = copy.deepcopy(self.value)
                hostile[key] = value
                self.reject(hostile)

    def test_passed_head_or_independent_review_claims_reject(self) -> None:
        hostile = copy.deepcopy(self.value)
        hostile["executionStatus"] = "passed"
        self.reject(hostile)
        hostile = copy.deepcopy(self.value)
        hostile["sourceIdentity"]["commit"] = "0" * 40
        self.reject(hostile)
        hostile = copy.deepcopy(self.value)
        hostile["partitions"][0]["reviewStatus"] = "approved"
        self.reject(hostile)

    def test_duplicate_missing_or_reordered_partition_reject(self) -> None:
        for mode in ("duplicate", "missing", "reordered"):
            hostile = copy.deepcopy(self.value)
            if mode == "duplicate":
                hostile["partitions"][-1] = copy.deepcopy(hostile["partitions"][0])
            elif mode == "missing":
                hostile["partitions"].pop()
            else:
                hostile["partitions"].reverse()
            self.reject(hostile)

    def test_missing_source_and_duplicate_ownership_reject(self) -> None:
        hostile = copy.deepcopy(self.value)
        hostile["partitions"][0]["sourcePaths"].pop(0)
        self.reject(hostile)
        hostile = copy.deepcopy(self.value)
        hostile["partitions"][1]["sourcePaths"].append(
            hostile["partitions"][0]["sourcePaths"][0]
        )
        self.reject(hostile)

    def test_cross_architecture_reassignment_and_missing_scope_reject(self) -> None:
        hostile = copy.deepcopy(self.value)
        path = hostile["partitions"][0]["sourcePaths"].pop(0)
        hostile["partitions"][1]["sourcePaths"].append(path)
        self.reject(hostile)
        hostile = copy.deepcopy(self.value)
        hostile["partitions"][0]["reviewGlobs"] = ["codex-rs/hepta-agentd/**"]
        self.reject(hostile)

    def test_qualification_record_cannot_cover_another_package_or_feature(self) -> None:
        for key, value in (
            ("package", "codex-hepta-learning-ledger"),
            ("requiredFeature", "other-feature"),
        ):
            original = copy.deepcopy(self.trace)
            try:
                self.trace["qualificationOnlyTests"][0][key] = value
                self.reject(copy.deepcopy(self.value))
            finally:
                self.trace = original

    def test_duplicate_requirement_or_test_declarations_cannot_hide_record_coverage(
        self,
    ) -> None:
        for key in ("requirements", "ordinaryProductTests", "qualificationOnlyTests"):
            original = copy.deepcopy(self.trace)
            try:
                self.trace[key].append(copy.deepcopy(self.trace[key][0]))
                self.reject(copy.deepcopy(self.value))
            finally:
                self.trace = original

    def test_missing_typed_profile_membership_and_commit_boundaries_reject(
        self,
    ) -> None:
        for path in REVIEW.REQUIRED_PARTITION_PATHS["B"]:
            hostile = copy.deepcopy(self.value)
            hostile["partitions"][1]["sourcePaths"].remove(path)
            self.reject(hostile)

    def test_nonexistent_absolute_or_escaping_source_and_scope_reject(self) -> None:
        for path in (
            "missing/source.rs",
            "/etc/passwd",
            "../outside.rs",
            "codex-rs/../outside.rs",
        ):
            hostile = copy.deepcopy(self.value)
            hostile["partitions"][0]["sourcePaths"].append(path)
            self.reject(hostile)
        hostile = copy.deepcopy(self.value)
        hostile["partitions"][0]["reviewGlobs"].append("../**")
        self.reject(hostile)

    def test_unknown_owner_requirements_or_records_reject(self) -> None:
        for key, value in (
            ("owner", "caller"),
            ("requirementIds", ["invented"]),
            ("requiredCommandRecords", ["fake-passed.json"]),
        ):
            hostile = copy.deepcopy(self.value)
            hostile["partitions"][0][key] = value
            self.reject(hostile)

    def test_omitted_required_test_record_rejects(self) -> None:
        hostile = copy.deepcopy(self.value)
        hostile["partitions"][0]["requiredCommandRecords"].remove(
            "agentd-default-tests.json"
        )
        self.reject(hostile)

    def test_omitted_requirement_allocation_and_empty_risks_reject(self) -> None:
        hostile = copy.deepcopy(self.value)
        hostile["partitions"][4]["requirementIds"] = []
        self.reject(hostile)
        hostile = copy.deepcopy(self.value)
        hostile["partitions"][0]["risks"] = []
        self.reject(hostile)


if __name__ == "__main__":
    unittest.main()
