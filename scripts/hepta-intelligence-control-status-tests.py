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
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "intelligence_status",
    Path(__file__).with_name("hepta-intelligence-control-status.py"),
)
assert SPEC is not None and SPEC.loader is not None
STATUS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATUS)


class CommandEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.head = "a" * 40
        self.git_patch = patch.object(
            STATUS,
            "checkout_identity",
            return_value={
                "commit": self.head,
                "tree": "b" * 40,
                "parents": [],
                "dirty": False,
            },
        )
        self.git_patch.start()
        self.environment_patch = patch.dict(STATUS.os.environ, {}, clear=True)
        self.environment_patch.start()
        self.command = STATUS.COMMANDS["intelligence-tests.json"]
        self.log = b"test canonical::tests::example ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored;\n"
        (self.root / "command.log").write_bytes(self.log)
        identity = {
            "commit": self.head,
            "tree": "b" * 40,
            "parents": [],
            "dirty": False,
        }
        self.record = {
            "schema_version": 1,
            "command": self.command,
            "working_directory": str((STATUS.ROOT / "codex-rs").resolve()),
            "run_id": None,
            "run_attempt": None,
            "job": None,
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
        self.environment_patch.stop()
        self.git_patch.stop()
        self.directory.cleanup()

    def admit(self, record: dict | None = None) -> tuple[dict, str]:
        path = self.root / "command.json"
        path.write_text(json.dumps(record or self.record), encoding="utf-8")
        return STATUS.validate_command_record(
            path, self.command, self.head, "source-head"
        )

    def test_exact_record_and_named_test_are_observed(self) -> None:
        _, text = self.admit()
        self.assertEqual(
            STATUS.observed_test_name(text, "example"), "canonical::tests::example"
        )

    def test_nonterminal_failed_and_wrong_source_records_are_rejected(self) -> None:
        for key, value in (
            ("status", "queued"),
            ("status", "failed"),
            ("status", "running"),
            ("exit_code", 1),
            ("command_exit_code", 1),
            ("tested_sha", "d" * 40),
            ("lane", "base-merge"),
            ("timed_out", True),
            ("observed_passed_tests", 0),
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

    def test_empty_or_failed_log_cannot_borrow_claimed_counts(self) -> None:
        for raw in (
            b"",
            b"test example ... ok\ntest result: FAILED. 1 passed; 1 failed;\n",
        ):
            (self.root / "command.log").write_bytes(raw)
            changed = copy.deepcopy(self.record)
            changed.update(
                log_bytes=len(raw), log_sha256=hashlib.sha256(raw).hexdigest()
            )
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.admit(changed)

    def test_self_consistent_wrong_checkout_metadata_is_rejected(self) -> None:
        for key, value in (("tree", "0" * 40), ("parents", ["c" * 40]), ("dirty", 0)):
            changed = copy.deepcopy(self.record)
            changed["before"][key] = changed["after"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.admit(changed)
        changed = copy.deepcopy(self.record)
        changed["working_directory"] = "/wrong-checkout"
        with self.assertRaises(ValueError):
            self.admit(changed)

    def test_boolean_counters_and_exit_codes_are_rejected(self) -> None:
        for key in (
            "exit_code",
            "command_exit_code",
            "observed_failed_tests",
            "schema_version",
            "log_bytes",
        ):
            changed = copy.deepcopy(self.record)
            changed[key] = False
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.admit(changed)

    def test_invocation_is_bound_when_ci_environment_is_present(self) -> None:
        with patch.dict(
            STATUS.os.environ,
            {
                "GITHUB_RUN_ID": "123",
                "GITHUB_RUN_ATTEMPT": "2",
                "GITHUB_JOB": "qualification",
            },
        ):
            with self.assertRaises(ValueError):
                self.admit()
            changed = copy.deepcopy(self.record)
            changed.update(run_id="123", run_attempt="2", job="qualification")
            self.admit(changed)

    def test_merge_record_requires_actual_parents_and_recomputed_tree(self) -> None:
        head = "d" * 40
        identity = {
            "commit": head,
            "tree": "b" * 40,
            "parents": ["c" * 40, self.head],
            "dirty": False,
        }
        record = copy.deepcopy(self.record)
        record.update(
            tested_sha=head,
            lane="base-merge",
            before=identity,
            after=copy.deepcopy(identity),
            recomputed_merge_tree="b" * 40,
        )
        path = self.root / "merge.json"
        with (
            patch.object(STATUS, "checkout_identity", return_value=identity),
            patch.object(STATUS, "git", return_value="b" * 40),
        ):
            path.write_text(json.dumps(record))
            STATUS.validate_command_record(path, self.command, head, "base-merge")
            record["recomputed_merge_tree"] = "e" * 40
            path.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                STATUS.validate_command_record(path, self.command, head, "base-merge")

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
        main = (STATUS.ROOT / "codex-rs/hepta-agentd/src/main.rs").read_text(
            encoding="utf-8"
        )
        config = (STATUS.ROOT / "codex-rs/hepta-agentd/src/config.rs").read_text(
            encoding="utf-8"
        )
        implementation = STATUS.load_json(STATUS.DOCS / "IMPLEMENTATION_MAP.json")
        self.assertNotIn("config.with_intelligence_product_runner", main)
        self.assertIn("with_canonical_intelligence_profile", main)
        self.assertIn("pub fn with_canonical_intelligence_profile", config)
        self.assertIn(
            "HostOwnedAgentdIntelligenceInvocationProviderV1::new(factory)", config
        )
        self.assertFalse(implementation["statusMatrix"]["defaultBinaryProfileComposed"])

    def test_canonical_profile_requires_rollback_and_process_containment(self) -> None:
        runner = (
            STATUS.ROOT / "codex-rs/hepta-agentd/src/intelligence_product_runner.rs"
        ).read_text(encoding="utf-8")
        signed_tests = (
            STATUS.ROOT
            / "codex-rs/hepta-agentd/src/intelligence_product_signed_tests.rs"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "self.authority_rollback.is_some() && self.hard_timeout_process_exit_grace.is_some()",
            runner,
        )
        self.assertIn("with_hard_timeout_process_exit", signed_tests)

    def test_production_profile_is_atomic_commit_bound_and_fail_closed(self) -> None:
        profile = (
            STATUS.ROOT / "codex-rs/hepta-agentd/src/intelligence_profile.rs"
        ).read_text(encoding="utf-8")
        runtime = (STATUS.ROOT / "codex-rs/hepta-agentd/src/runtime.rs").read_text(
            encoding="utf-8"
        )
        self.assertIn("AgentdCanonicalIntelligenceProductionProfileV1", profile)
        self.assertIn("AgentdCanonicalIntelligenceCompositionReceiptV1", profile)
        self.assertIn("source_commit", profile)
        self.assertIn("capability_profile_digest", profile)
        self.assertIn("with_canonical_intelligence_profile", profile)
        self.assertIn("with_intelligence_learning_runtime", profile)
        self.assertIn("with_intelligence_execution_host", profile)
        self.assertIn("validate_runtime_profile_shape", runtime)
        self.assertIn(
            "runner and invocation provider must be installed atomically", profile
        )
        self.assertIn(
            "physical execution and durable learning recovery must be installed together",
            profile,
        )

    def test_unknown_commit_and_candidate_membership_are_typed(self) -> None:
        commit = (
            STATUS.ROOT / "codex-rs/hepta-agentd/src/intelligence_commit_state.rs"
        ).read_text(encoding="utf-8")
        membership = (
            STATUS.ROOT / "codex-rs/hepta-agentd/src/intelligence_membership.rs"
        ).read_text(encoding="utf-8")
        integrity = (
            STATUS.ROOT / "codex-rs/hepta-agentd/src/intelligence_prepared_integrity.rs"
        ).read_text(encoding="utf-8")
        self.assertIn("UnknownCommittedState", commit)
        self.assertIn("pub const fn is_terminal", commit)
        self.assertIn("AgentdLegalCandidateMembershipProofV1", membership)
        self.assertIn("canonical.sort()", membership)
        self.assertIn("selected candidate absent", membership)
        self.assertIn("AgentdLegalCandidateMembershipProofV1::admit", integrity)

    def test_currentness_snapshot_is_fence_scoped(self) -> None:
        canonical = (
            STATUS.ROOT / "codex-rs/hepta-intelligence/src/canonical.rs"
        ).read_text(encoding="utf-8")
        product = (
            STATUS.ROOT / "codex-rs/hepta-agentd/src/intelligence_product.rs"
        ).read_text(encoding="utf-8")
        self.assertIn("fn refresh_snapshot", canonical)
        self.assertIn("require_current_from_snapshot", canonical)
        self.assertIn(
            "snapshot: Option<BTreeMap<StableId, CurrentOwnerStateV1>>", product
        )
        self.assertIn("self.snapshot = Some(self.load_snapshot(owner_id)?)", product)
        self.assertIn(
            "validate_current_snapshot(&request.snapshot, oracle)?", canonical
        )

    def test_product_document_preserves_completion_taxonomy(self) -> None:
        product = (STATUS.DOCS / "PRODUCT_CLOSURE.md").read_text(encoding="utf-8")
        for state in (
            "source_present",
            "repo_native_composed",
            "physically_executed",
            "independently_qualified",
            "activated",
            "released",
        ):
            self.assertIn(state, product)
        self.assertIn("ordinary CLI remains uncomposed", product)
        self.assertIn("UnknownCommittedState", product)
        self.assertIn("one bounded open/read/parse", product)

    def test_current_generation_run_start_recovery_uses_the_product_route(self) -> None:
        objective = (
            STATUS.ROOT / "codex-rs/hepta-agentd/src/objective_runtime.rs"
        ).read_text(encoding="utf-8")
        runtime = (STATUS.ROOT / "codex-rs/hepta-agentd/src/runtime.rs").read_text(
            encoding="utf-8"
        )
        self.assertIn("pub(crate) async fn reconcile", objective)
        self.assertIn(".records()", objective)
        self.assertIn(".cloned()", objective)
        self.assertIn(".start_canonical_intelligence(&record)", objective)
        self.assertIn("complete_canonical_intelligence(ready).await", objective)
        self.assertIn("host.reconcile(", runtime)
        self.assertIn(".await?;", runtime)
        self.assertNotIn(
            "must wait for the authenticated ObjectiveStart retry", objective
        )


if __name__ == "__main__":
    unittest.main()
