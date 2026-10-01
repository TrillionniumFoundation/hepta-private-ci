#!/usr/bin/env python3
"""Adversarial tests for downloaded lane evidence and acceptance receipts."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "intelligence_readiness",
    Path(__file__).with_name("hepta-intelligence-readiness.py"),
)
assert SPEC is not None and SPEC.loader is not None
READINESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READINESS)
STATUS = READINESS.STATUS
ACCEPTANCE = READINESS.ACCEPTANCE


class LaneEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.head, self.base = "a" * 40, "c" * 40
        self.identity = {
            "commit": self.head,
            "tree": "b" * 40,
            "parents": [],
            "dirty": False,
        }
        self.invocation = {"run_id": "123", "run_attempt": "2", "job": "qualification"}
        self.trace = STATUS.load_json(STATUS.DOCS / "TEST_TRACEABILITY.json")
        names = {name: set() for name in STATUS.COMMANDS}
        for rows, legacy in (
            (self.trace["ordinaryProductTests"], False),
            (self.trace["qualificationOnlyTests"], True),
        ):
            for test in rows:
                name = (
                    "agentd-qualification-tests.json"
                    if legacy
                    else STATUS.PACKAGE_RECORDS[test["package"]]
                )
                names[name].add(test["name"])
        for objective in ACCEPTANCE.OBJECTIVES:
            for test in objective["directTests"]:
                names[STATUS.PACKAGE_RECORDS[test["package"]]].add(test["name"])
        for name, command in STATUS.COMMANDS.items():
            tests = names[name] or ({"sentinel"} if command[1] == "test" else set())
            raw = "".join(f"test fixture::{test} ... ok\n" for test in sorted(tests))
            if tests:
                raw += f"test result: ok. {len(tests)} passed; 0 failed; 0 ignored;\n"
            encoded = raw.encode()
            (self.root / (name + ".log")).write_bytes(encoded)
            record = {
                "schema_version": 1,
                "command": command,
                "tested_sha": self.head,
                "source_sha": self.head,
                "base_sha": self.base,
                "lane": "source-head",
                "working_directory": str((STATUS.ROOT / "codex-rs").resolve()),
                **self.invocation,
                "status": "passed",
                "command_exit_code": 0,
                "exit_code": 0,
                "timed_out": False,
                "output_limit_exceeded": False,
                "before": self.identity,
                "after": copy.deepcopy(self.identity),
                "log_file": name + ".log",
                "log_bytes": len(encoded),
                "log_sha256": hashlib.sha256(encoded).hexdigest(),
                "observed_passed_tests": len(tests),
                "observed_failed_tests": 0,
            }
            self.write(name, record)

        # Use the production receipt emitter so the baseline is its real format.
        def fake_git(*args: str) -> str:
            if args == ("rev-parse", "HEAD"):
                return self.head
            if args[0] == "status":
                return ""
            return "b" * 40

        with (
            patch.object(STATUS, "git", side_effect=fake_git),
            patch.object(STATUS, "checkout_identity", return_value=self.identity),
            patch.dict(
                STATUS.os.environ,
                {
                    "GITHUB_RUN_ID": "123",
                    "GITHUB_RUN_ATTEMPT": "2",
                    "GITHUB_JOB": "qualification",
                },
                clear=True,
            ),
            patch.object(
                ACCEPTANCE,
                "validate_objectives",
                return_value=(
                    STATUS.load_json(STATUS.DOCS / "IMPLEMENTATION_MAP.json"),
                    self.trace,
                ),
            ),
        ):
            ACCEPTANCE.emit_receipt(
                self.head,
                "source-head",
                self.root,
                self.root / "ACCEPTANCE_RECEIPT.json",
            )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def write(self, name: str, value: dict) -> None:
        (self.root / name).write_text(json.dumps(value), encoding="utf-8")

    def inspect(self, root: Path | None = None) -> dict:
        return READINESS.validate_lane(
            self.root if root is None else root,
            "source-head",
            self.identity,
            self.head,
            self.base,
            self.invocation,
            self.trace,
        )

    def test_production_receipt_and_all_named_observations_are_admitted(self) -> None:
        result = self.inspect()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(set(result["commandHashes"]), set(STATUS.COMMANDS))
        self.assertIn("ACCEPTANCE_RECEIPT.json", result["artifactHashes"])

    def test_empty_receipt_and_vacuous_results_do_not_pass(self) -> None:
        for receipt in ({}, {"status": "passed"}, {"results": []}, {"objectives": []}):
            self.write("ACCEPTANCE_RECEIPT.json", receipt)
            with self.subTest(receipt=receipt):
                self.assertEqual(self.inspect()["status"], "missing_or_failed")

    def test_receipt_cannot_substitute_source_lane_or_external_claims(self) -> None:
        original = STATUS.load_json(self.root / "ACCEPTANCE_RECEIPT.json")
        for container, key, value in (
            ("sourceIdentity", "commit", "d" * 40),
            ("sourceIdentity", "lane", "base-merge"),
            ("sourceIdentity", "commitMustEqualCheckoutHead", 1),
            ("claimBoundary", "productionQualified", True),
            ("claimBoundary", "realProcessProviderE2E", True),
            ("claimBoundary", "activation", 0),
        ):
            changed = copy.deepcopy(original)
            changed[container][key] = value
            self.write("ACCEPTANCE_RECEIPT.json", changed)
            with self.subTest(key=key):
                self.assertEqual(self.inspect()["status"], "missing_or_failed")

    def test_receipt_objectives_and_observed_tests_are_not_optional(self) -> None:
        original = STATUS.load_json(self.root / "ACCEPTANCE_RECEIPT.json")
        for key, value in (
            ("observedTests", {}),
            ("status", "pending"),
            ("commandLogSha256", {}),
        ):
            changed = copy.deepcopy(original)
            changed["objectives"][0][key] = value
            self.write("ACCEPTANCE_RECEIPT.json", changed)
            self.assertEqual(self.inspect()["status"], "missing_or_failed")
        changed = copy.deepcopy(original)
        changed["objectives"] = changed["objectives"][:-1]
        self.write("ACCEPTANCE_RECEIPT.json", changed)
        self.assertEqual(self.inspect()["status"], "missing_or_failed")
        changed = copy.deepcopy(original)
        changed["objectiveDefinitionSha256"] = "0" * 64
        self.write("ACCEPTANCE_RECEIPT.json", changed)
        self.assertEqual(self.inspect()["status"], "missing_or_failed")

    def test_merge_lane_requires_exact_candidate_and_recomputed_tree(self) -> None:
        identity = {
            "commit": "d" * 40,
            "tree": "b" * 40,
            "parents": [self.base, self.head],
            "dirty": False,
        }
        for name in STATUS.COMMANDS:
            record = STATUS.load_json(self.root / name)
            record.update(
                tested_sha=identity["commit"],
                lane="base-merge",
                before=identity,
                after=copy.deepcopy(identity),
                recomputed_merge_tree=identity["tree"],
            )
            self.write(name, record)
        receipt = STATUS.load_json(self.root / "ACCEPTANCE_RECEIPT.json")
        receipt["sourceIdentity"].update(commit=identity["commit"], lane="base-merge")
        self.write("ACCEPTANCE_RECEIPT.json", receipt)
        with patch.object(STATUS, "git", return_value=identity["tree"]):
            result = READINESS.validate_lane(
                self.root,
                "base-merge",
                identity,
                self.head,
                self.base,
                self.invocation,
                self.trace,
            )
            self.assertEqual(result["status"], "passed")
            record = STATUS.load_json(self.root / "fmt.json")
            record["recomputed_merge_tree"] = "e" * 40
            self.write("fmt.json", record)
            result = READINESS.validate_lane(
                self.root,
                "base-merge",
                identity,
                self.head,
                self.base,
                self.invocation,
                self.trace,
            )
            self.assertEqual(result["status"], "missing_or_failed")

    def test_command_cannot_borrow_a_different_run_attempt_job_or_source(self) -> None:
        original = STATUS.load_json(self.root / "fmt.json")
        for key, value in (
            ("run_id", "124"),
            ("run_attempt", "1"),
            ("job", "readiness-manifest"),
            ("source_sha", "d" * 40),
            ("base_sha", "d" * 40),
            ("tested_sha", "d" * 40),
            ("command", ["true"]),
            ("working_directory", "/arbitrary-checkout/codex-rs"),
        ):
            changed = copy.deepcopy(original)
            changed[key] = value
            self.write("fmt.json", changed)
            with self.subTest(key=key):
                self.assertEqual(self.inspect()["status"], "missing_or_failed")

    def test_failed_log_cannot_borrow_unchanged_record_counts(self) -> None:
        name = "intelligence-tests.json"
        record = STATUS.load_json(self.root / name)
        raw = (
            self.root / record["log_file"]
        ).read_bytes() + b"test result: FAILED. 0 passed; 1 failed;\n"
        (self.root / record["log_file"]).write_bytes(raw)
        record.update(log_bytes=len(raw), log_sha256=hashlib.sha256(raw).hexdigest())
        self.write(name, record)
        self.assertEqual(self.inspect()["status"], "missing_or_failed")

    def test_duplicate_artifacts_and_symlinks_are_rejected(self) -> None:
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "fmt.json").write_bytes((self.root / "fmt.json").read_bytes())
        self.assertEqual(self.inspect()["status"], "missing_or_failed")
        (nested / "fmt.json").unlink()
        (nested / "linked.log").symlink_to(self.root / "fmt.json.log")
        self.assertEqual(self.inspect()["status"], "missing_or_failed")

    def test_absent_lane_stays_missing(self) -> None:
        self.assertEqual(
            self.inspect(self.root / "absent")["status"], "missing_or_failed"
        )
        for number in ("", "0", "untrusted"):
            with self.subTest(number=number), self.assertRaises(ValueError):
                READINESS.deterministic_merge_identity(self.base, self.head, number)


if __name__ == "__main__":
    unittest.main()
