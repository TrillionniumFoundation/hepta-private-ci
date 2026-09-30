#!/usr/bin/env python3
"""Adversarial regressions for retained operator execution witnesses."""

import argparse
import contextlib
import copy
import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MAP = importlib.import_module("hepta-learning-operator-map")
STAGE = importlib.import_module("hepta-learning-operator-stage")
RECEIPT = importlib.import_module("hepta-learning-operator-receipt")
READINESS = importlib.import_module("hepta-learning-operator-readiness")
EVIDENCE = importlib.import_module("hepta-learning-operator-evidence")


class OperatorEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.env = dict(
            os.environ,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_AUTHOR_NAME="hepta-learning-operator-ci",
            GIT_AUTHOR_EMAIL="hepta-learning-operator-ci@users.noreply.github.com",
            GIT_COMMITTER_NAME="hepta-learning-operator-ci",
            GIT_COMMITTER_EMAIL="hepta-learning-operator-ci@users.noreply.github.com",
            GIT_AUTHOR_DATE="2000-01-01T00:00:00Z",
            GIT_COMMITTER_DATE="2000-01-01T00:00:00Z",
        )
        for module in (MAP, STAGE, RECEIPT, READINESS, EVIDENCE):
            self.stack.enter_context(mock.patch.object(module, "ROOT", self.root))
        self.canonical = (
            self.root / "docs/modules/learning.operator/IMPLEMENTATION_MAP.json"
        )
        self.stack.enter_context(
            mock.patch.object(MAP, "CANONICAL_MAP", self.canonical)
        )
        source_paths = sorted(
            set(READINESS.DOCUMENT_PATHS)
            | {
                "source.rs",
                "codex-rs/Cargo.lock",
                ".github/workflows/learning-operator-authoritative.yml",
            }
        )
        self.stack.enter_context(
            mock.patch.object(MAP, "mapped_paths", return_value=source_paths)
        )
        for path in source_paths:
            self.write(path, "{}\n" if path.endswith(".json") else "fixture\n")
        self.write(
            str(self.canonical.relative_to(self.root)),
            json.dumps(
                {
                    "module": "learning.operator",
                    "operations": [],
                    "productCallers": [],
                    "claimBoundary": {"activation": False, "release": False},
                    "productCallerState": "owner_ports_uncomposed",
                    "productionWriterState": "not_established",
                }
            ),
        )
        self.git("init", "--quiet")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.write("source.rs", "source candidate\n")
        self.git("add", "source.rs")
        self.git("commit", "--quiet", "-m", "source")
        self.source = self.git("rev-parse", "HEAD")
        self.tree = self.git("rev-parse", "HEAD^{tree}")
        self.synthetic = self.git(
            "commit-tree",
            self.tree,
            "-p",
            self.base,
            "-p",
            self.source,
            input="learning.operator deterministic synthetic merge\n",
        )
        self.output = self.root / ".evidence/readiness-manifest.json"
        self.map_path = self.root / ".evidence/implementation-map.json"
        MAP.generate(self.source, self.tree, self.map_path)
        self.write(".evidence/rustc.txt", "host: fixture-target\n")
        self.write(".evidence/runner.txt", "fixture runner\n")
        self.write(".evidence/test-set.json", "{}\n")
        for name in READINESS.REQUIRED_STAGES:
            self.record(name)
        self.receipt_args = argparse.Namespace(
            source_sha=self.source,
            source_tree=self.tree,
            workflow_path=".github/workflows/learning-operator-authoritative.yml",
            workflow_blob=self.git(
                "rev-parse",
                f"{self.source}:.github/workflows/learning-operator-authoritative.yml",
            ),
            workflow_run_id="42",
            workflow_run_attempt="1",
            main_sha=self.base,
            synthetic_sha=self.synthetic,
            synthetic_tree=self.tree,
            target="fixture-target",
            rustc_file=".evidence/rustc.txt",
            runner_file=".evidence/runner.txt",
            test_set_file=".evidence/test-set.json",
            implementation_map=".evidence/implementation-map.json",
            output=".evidence/qualification-manifest.json",
            evidence=[],
        )
        self.generate_gates()
        RECEIPT.emit(self.receipt_args)
        self.readiness_args = argparse.Namespace(
            source_head_sha=self.source,
            frozen_source_sha=self.source,
            observation_head_sha=self.source,
            source_tree_hash=self.tree,
            base_sha=self.base,
            deterministic_merge_sha=self.synthetic,
            github_merge_sha=self.source,
            workflow_sha=self.receipt_args.workflow_blob,
            workflow_path=self.receipt_args.workflow_path,
            workflow_run_id="42",
            attempt_id="1",
            runner_image="fixture",
            target_triple="fixture-target",
            toolchain_file=".evidence/rustc.txt",
            test_set_file=".evidence/test-set.json",
            implementation_map=".evidence/implementation-map.json",
            stage_directory=".evidence/stages",
            output=".evidence/readiness-manifest.json",
        )
        READINESS.emit(self.readiness_args)

    def git(self, *args, input=None):
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            env=self.env,
            input=input,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def record(self, stage, status="passed", code=0):
        log = f".evidence/{stage}.log"
        if not (self.root / log).exists():
            self.write(log, "retained executed stage log\n")
        STAGE.record(
            argparse.Namespace(
                stage=stage,
                source_sha=self.source,
                source_tree=self.tree,
                workflow_run_id="42",
                run_attempt="1",
                status=status,
                exit_code=code,
                reason="" if status == "passed" else "executed command failed",
                command=f"fixture execute {stage}",
                log=log,
                output=f".evidence/stages/{stage}.json",
            )
        )

    def generate_gates(self):
        self.receipt_args.evidence = []
        for name, stage_name in RECEIPT.GATE_STAGES.items():
            stage_path = f".evidence/stages/{stage_name}.json"
            stage = json.loads((self.root / stage_path).read_text())
            log = self.root / stage["log"]["path"]
            raw = log.read_bytes()
            gate = {
                "schema": "hepta.learning-operator-qualification-gate.v2",
                "schemaVersion": 2,
                "module": "learning.operator",
                "gate": name,
                "sourceSha": self.source,
                "sourceTree": self.tree,
                "command": stage["command"],
                "commandSha256": stage["commandSha256"],
                "executionIdentity": stage["executionIdentity"],
                "gatePurpose": name,
                "target": self.receipt_args.target,
                "status": "pass",
                "stageStatus": "passed",
                "stageReceipt": {
                    "path": stage_path,
                    "sha256": RECEIPT.sha256(self.root / stage_path),
                },
                "log": {
                    "path": stage["log"]["path"],
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                    "lines": raw.count(b"\n"),
                },
            }
            relative = f".evidence/gates/{name}.json"
            self.write(relative, json.dumps(gate))
            self.receipt_args.evidence.append(f"{name}={relative}")

    def resign_readiness(self, payload):
        payload.pop("manifest_sha256", None)
        payload["manifest_sha256"] = READINESS.digest_bytes(
            MAP.canonical_bytes(payload)
        )
        self.output.write_text(json.dumps(payload), encoding="utf-8")

    def test_complete_retained_witnesses_qualify_engineering_only(self):
        payload = json.loads(self.output.read_text())
        self.assertTrue(payload["engineeringQualified"])
        self.assertTrue(payload["identity_verified"])
        self.assertFalse(payload["productionQualified"])
        READINESS.verify_path(self.output)

    def test_recomputing_aggregate_cannot_turn_failed_stage_into_passed(self):
        self.record("compile", "failed", 7)
        READINESS.emit(self.readiness_args)
        payload = json.loads(self.output.read_text())
        self.assertFalse(payload["engineeringQualified"])
        payload["stage_statuses"]["compile"]["status"] = "passed"
        payload["engineeringQualified"] = payload["mergeReady"] = True
        self.resign_readiness(payload)
        with self.assertRaises(ValueError):
            READINESS.verify_path(self.output)

    def test_missing_and_changed_logs_reject_even_with_recomputed_inventory(self):
        log = self.root / ".evidence/compile.log"
        original = log.read_bytes()
        for missing in (False, True):
            with self.subTest(missing=missing):
                if missing:
                    log.unlink()
                else:
                    log.write_bytes(original + b"changed\n")
                payload = json.loads(self.output.read_text())
                payload["artifact_hashes"] = READINESS.artifact_hashes(
                    self.output.parent, self.output
                )
                self.resign_readiness(payload)
                with self.assertRaises(ValueError):
                    READINESS.verify_path(self.output)
                log.write_bytes(original)

    def test_gate_producer_binds_executed_command_and_keeps_purpose_as_description(
        self,
    ):
        arguments = [
            "gate-producer",
            "--name",
            "module-tests",
            "--source-sha",
            self.source,
            "--source-tree",
            self.tree,
            "--command",
            "a descriptive gate purpose",
            "--log",
            ".evidence/unit_tests.log",
            "--status-file",
            ".evidence/stages/unit_tests.json",
            "--output",
            ".evidence/producer-test.json",
            "--target",
            self.receipt_args.target,
        ]
        with mock.patch.object(sys, "argv", arguments):
            EVIDENCE.main()
        gate = json.loads((self.root / ".evidence/producer-test.json").read_text())
        self.assertEqual(gate["gatePurpose"], "a descriptive gate purpose")
        self.assertEqual(gate["command"], "fixture execute unit_tests")
        RECEIPT.verify_gate(
            gate,
            "module-tests",
            self.source,
            self.tree,
            "42",
            "1",
            expected_target=self.receipt_args.target,
        )

    def test_receipt_cannot_relabel_another_command_as_the_gate(self):
        path = self.root / ".evidence/gates/module-tests.json"
        gate = json.loads(path.read_text())
        gate["command"] = "different unchecked command"
        gate["commandSha256"] = hashlib.sha256(gate["command"].encode()).hexdigest()
        with self.assertRaises(ValueError):
            RECEIPT.verify_gate(
                gate,
                "module-tests",
                self.source,
                self.tree,
                "42",
                "1",
                expected_target=self.receipt_args.target,
            )

    def test_old_source_or_run_stage_cannot_be_rewrapped(self):
        path = self.root / ".evidence/stages/unit_tests.json"
        original = json.loads(path.read_text())
        for key, changed in (
            ("sourceSha", self.base),
            ("workflowRunId", "previous-run"),
        ):
            with self.subTest(field=key):
                stage = copy.deepcopy(original)
                stage["executionIdentity"][key] = changed
                path.write_text(json.dumps(stage))
                gate = json.loads(
                    (self.root / ".evidence/gates/module-tests.json").read_text()
                )
                gate["stageReceipt"]["sha256"] = RECEIPT.sha256(path)
                with self.assertRaises(ValueError):
                    RECEIPT.verify_gate(
                        gate,
                        "module-tests",
                        self.source,
                        self.tree,
                        "42",
                        "1",
                        expected_target=self.receipt_args.target,
                    )

    def test_exact_source_receipt_cannot_reuse_another_execution_identity(self):
        path = self.root / ".evidence/stages/exact_source_receipt.json"
        original = json.loads(path.read_text())
        for key, changed in (
            ("sourceSha", self.base),
            ("sourceTree", self.git("rev-parse", f"{self.base}^{{tree}}")),
            ("workflowRunId", "previous-run"),
            ("runAttempt", "2"),
        ):
            with self.subTest(field=key):
                stage = copy.deepcopy(original)
                stage["executionIdentity"][key] = changed
                path.write_text(json.dumps(stage))
                payload = json.loads(self.output.read_text())
                payload["stage_statuses"]["exact_source_receipt"]["receipt_sha256"] = (
                    READINESS.digest_file(path)
                )
                payload["artifact_hashes"] = READINESS.artifact_hashes(
                    self.output.parent, self.output
                )
                self.resign_readiness(payload)
                with self.assertRaises(ValueError):
                    READINESS.verify_path(self.output)

    def test_correct_parent_order_does_not_accept_arbitrary_merge_tree(self):
        wrong = self.git(
            "commit-tree",
            self.git("rev-parse", f"{self.base}^{{tree}}"),
            "-p",
            self.base,
            "-p",
            self.source,
            input="learning.operator deterministic synthetic merge\n",
        )
        with self.assertRaises(ValueError):
            RECEIPT.verify_synthetic_merge(self.source, self.base, wrong)

    def test_unknown_merge_is_an_explicit_unqualified_failure_report(self):
        self.record("deterministic_merge", "failed", 1)
        self.readiness_args.deterministic_merge_sha = "0" * 40
        READINESS.emit(self.readiness_args)
        payload = json.loads(self.output.read_text())
        self.assertFalse(payload["identity_verified"])
        self.assertFalse(payload["engineeringQualified"])
        self.assertTrue(payload["identity_errors"])
        READINESS.verify_path(self.output)
        with self.assertRaises(ValueError):
            READINESS.verify_path(self.output, require_qualified=True)

    def test_worktree_controls_must_match_the_claimed_source_objects(self):
        self.write("source.rs", "altered after source freeze\n")
        with self.assertRaises(subprocess.CalledProcessError):
            MAP.verify(self.map_path, expected_sha=self.source, expected_tree=self.tree)

    def test_readiness_cannot_mix_another_targets_qualified_receipt(self):
        payload = json.loads(self.output.read_text())
        payload["target_triple"] = "different-target"
        self.resign_readiness(payload)
        with self.assertRaises(ValueError):
            READINESS.verify_path(self.output)

    def test_gate_target_drift_rejects_with_all_evidence_hashes_recomputed(self):
        path = self.root / ".evidence/gates/target-build.json"
        gate = json.loads(path.read_text())
        gate["target"] = "different-target"
        path.write_text(json.dumps(gate))

        manifest_path = self.root / self.receipt_args.output
        manifest = json.loads(manifest_path.read_text())
        for row in manifest["evidence"]:
            if row["name"] == "target-build":
                row["sha256"] = RECEIPT.sha256(path)
        manifest.pop("aggregateEvidenceSha256")
        manifest["aggregateEvidenceSha256"] = hashlib.sha256(
            RECEIPT.canonical_bytes(manifest)
        ).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "gate target differs from compiler"):
            RECEIPT.verify(manifest_path)

        readiness = json.loads(self.output.read_text())
        readiness["artifact_hashes"] = READINESS.artifact_hashes(
            self.output.parent, self.output
        )
        self.resign_readiness(readiness)
        with self.assertRaisesRegex(ValueError, "gate target differs from compiler"):
            READINESS.verify_path(self.output)

    def test_stage_pass_requires_zero_exit_status(self):
        path = self.root / ".evidence/stages/unit_tests.json"
        stage = json.loads(path.read_text())
        stage["exitCode"] = 8
        with self.assertRaises(ValueError):
            STAGE.verify_value(stage, "unit_tests")


if __name__ == "__main__":
    unittest.main()
