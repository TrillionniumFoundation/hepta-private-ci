#!/usr/bin/env python3
"""Unit tests for intelligence execution-record admission, not native receipts."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "intelligence_status", Path(__file__).with_name("hepta-intelligence-control-status.py")
)
assert SPEC is not None and SPEC.loader is not None
STATUS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATUS)


class CommandEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.head = "a" * 40
        self.command = STATUS.COMMANDS["intelligence-tests.json"]
        self.log = b"test canonical::tests::example ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored;\n"
        (self.root / "command.log").write_bytes(self.log)
        identity = {"commit": self.head, "tree": "b" * 40, "parents": [], "dirty": False}
        self.record = {
            "command": self.command,
            "tested_sha": self.head,
            "source_sha": self.head,
            "base_sha": "c" * 40,
            "lane": "source-head",
            "status": "passed",
            "command_exit_code": 0,
            "exit_code": 0,
            "timed_out": False,
            "output_limit_exceeded": False,
            "before": identity,
            "after": copy.deepcopy(identity),
            "log_file": "command.log",
            "log_bytes": len(self.log),
            "log_sha256": hashlib.sha256(self.log).hexdigest(),
            "observed_passed_tests": 1,
            "observed_failed_tests": 0,
        }

    def tearDown(self) -> None:
        self.directory.cleanup()

    def admit(self, record: dict | None = None) -> tuple[dict, str]:
        path = self.root / "command.json"
        path.write_text(json.dumps(record or self.record), encoding="utf-8")
        return STATUS.validate_command_record(path, self.command, self.head, "source-head")

    def test_exact_record_and_named_test_are_observed(self) -> None:
        _, text = self.admit()
        self.assertEqual(STATUS.observed_test_name(text, "example"), "canonical::tests::example")

    def test_nonterminal_failed_and_wrong_source_records_are_rejected(self) -> None:
        for key, value in (
            ("status", "queued"), ("status", "failed"), ("status", "running"),
            ("exit_code", 1), ("command_exit_code", 1), ("tested_sha", "d" * 40),
            ("lane", "base-merge"), ("timed_out", True), ("observed_passed_tests", 0),
        ):
            changed = copy.deepcopy(self.record)
            changed[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.admit(changed)

    def test_changed_checkout_and_log_are_rejected(self) -> None:
        changed = copy.deepcopy(self.record)
        changed["after"]["dirty"] = True
        with self.assertRaises(ValueError):
            self.admit(changed)
        (self.root / "command.log").write_bytes(self.log + b"substituted")
        with self.assertRaises(ValueError):
            self.admit()

    def test_missing_ignored_and_ambiguous_test_passes_are_rejected(self) -> None:
        for text in (
            "test something_else ... ok\n",
            "test example ... ignored\n",
            "test one::example ... ok\ntest two::example ... ok\n",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                STATUS.observed_test_name(text, "example")

    def test_pass_projection_requires_real_command_records(self) -> None:
        with self.assertRaises(ValueError):
            STATUS.project_execution({}, {}, self.head, "source-head", "passed", None)

    def test_log_path_cannot_escape_record_directory(self) -> None:
        changed = copy.deepcopy(self.record)
        changed["log_file"] = "../command.log"
        with self.assertRaises(ValueError):
            self.admit(changed)


class SourceMappingTests(unittest.TestCase):
    def test_current_reviewed_mappings_resolve(self) -> None:
        implementation, trace = STATUS.validate_declarations()
        self.assertFalse(implementation["statusMatrix"]["allRequirementsClosed"])
        self.assertTrue(trace["ordinaryProductTests"])
        self.assertTrue(trace["qualificationOnlyTests"])

    def test_standalone_binary_cannot_install_a_runner_only_profile(self) -> None:
        main = (STATUS.ROOT / "codex-rs/hepta-agentd/src/main.rs").read_text(encoding="utf-8")
        config = (STATUS.ROOT / "codex-rs/hepta-agentd/src/config.rs").read_text(encoding="utf-8")
        implementation = STATUS.load_json(STATUS.DOCS / "IMPLEMENTATION_MAP.json")
        self.assertNotIn("config.with_intelligence_product_runner", main)
        self.assertIn("with_canonical_intelligence_profile", main)
        self.assertIn("pub fn with_canonical_intelligence_profile", config)
        self.assertIn("HostOwnedAgentdIntelligenceInvocationProviderV1::new(factory)", config)
        self.assertFalse(implementation["statusMatrix"]["defaultBinaryProfileComposed"])


if __name__ == "__main__":
    unittest.main()
