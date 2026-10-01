#!/usr/bin/env python3
"""Adversarial regressions for retained operator execution witnesses."""

import argparse
import contextlib
import copy
import hashlib
import importlib
import json
import os
import re
import shlex
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
CONTRACT = importlib.import_module("hepta-learning-operator-contract")


class QualificationRunnerTests(unittest.TestCase):
    def authoritative_source(self):
        return (
            Path(__file__).with_name("hepta-learning-operator-authoritative.sh")
        ).read_text(encoding="utf-8")

    def test_authoritative_runner_installs_every_pinned_execution_tool(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/learning-operator-authoritative.yml"
        ).read_text(encoding="utf-8")
        CONTRACT.verify_qualification_tools(workflow)
        for tool in ("cargo-llvm-cov@0.9.1", "just@1.51.0", "nextest@0.9.103"):
            with self.subTest(tool=tool), self.assertRaises(SystemExit):
                CONTRACT.verify_qualification_tools(workflow.replace(tool, "missing"))

    def test_product_dependency_changes_trigger_operator_audit(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/hepta-learning-operator-audit.yml"
        ).read_text(encoding="utf-8")
        CONTRACT.verify_product_ci_scope(workflow)
        for root in MAP.PRODUCT_DEPENDENCY_ROOTS:
            with self.subTest(root=root), self.assertRaises(SystemExit):
                CONTRACT.verify_product_ci_scope(workflow.replace(f"- '{root}/**'", ""))

    def test_v8_provisioning_runs_before_native_qualification(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/learning-operator-authoritative.yml"
        ).read_text(encoding="utf-8")
        CONTRACT.verify_v8_provisioning(workflow)
        for token in (
            "run: python3 scripts/hepta_ci_v8.py",
            "CODEX_REPO_ROOT: ${{ github.workspace }}",
            "PYTHONPATH: scripts",
        ):
            with self.subTest(token=token), self.assertRaises(SystemExit):
                CONTRACT.verify_v8_provisioning(workflow.replace(token, "missing"))
        step = re.search(
            r"(?ms)^      - name: Prepare checksum-verified V8 archive and binding\n.*?(?=^      - name:)",
            workflow,
        ).group()
        for changed in (
            workflow.replace(step, "") + step,
            workflow.replace(
                step, step.replace("        env:", "        if: false\n        env:")
            ),
        ):
            with self.subTest(workflow=changed), self.assertRaises(SystemExit):
                CONTRACT.verify_v8_provisioning(changed)

    def test_v8_resolver_controls_are_mapped_and_trigger_operator_audit(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/hepta-learning-operator-audit.yml"
        ).read_text(encoding="utf-8")
        mapped = MAP.mapped_paths({})
        controls = {
            "scripts/hepta_ci_v8.py": "scripts/hepta_ci_v8.py",
            "scripts/test_hepta_ci_v8.py": "scripts/test_hepta_ci_v8.py",
            "scripts/codex_package": "scripts/codex_package/**",
        }
        for path, trigger in controls.items():
            with self.subTest(path=path):
                self.assertIn(path, mapped)
                with self.assertRaises(SystemExit):
                    CONTRACT.verify_product_ci_scope(
                        workflow.replace(f"- '{trigger}'", "")
                    )

    def test_status_projection_rejects_numeric_boolean_imitation(self):
        status_raw = CONTRACT.read(CONTRACT.STATUS_PATH)
        status = json.loads(status_raw)
        implementation = CONTRACT.load_json(CONTRACT.MAP_PATH)
        implementation["statusProjectionSha256"] = CONTRACT.sha256_text(status_raw)
        original_load = CONTRACT.load_json
        original_read = CONTRACT.read

        def check(row):
            with (
                mock.patch.object(
                    CONTRACT,
                    "load_json",
                    side_effect=lambda path: (
                        row if path == CONTRACT.MAP_PATH else original_load(path)
                    ),
                ),
                mock.patch.object(
                    CONTRACT,
                    "read",
                    side_effect=lambda path: (
                        status_raw
                        if path == CONTRACT.STATUS_PATH
                        else original_read(path)
                    ),
                ),
            ):
                CONTRACT.verify_status_projection(status)

        check(implementation)
        for key in (
            "activation",
            "shadowCoordinatorImplemented",
            "defaultProductLoopWired",
        ):
            old = implementation["claimBoundary"][key]
            for value in (int(old), float(old)):
                with self.subTest(key=key, type=type(value).__name__):
                    tampered = copy.deepcopy(implementation)
                    tampered["claimBoundary"][key] = value
                    with self.assertRaises(SystemExit):
                        check(tampered)
        for value in (0, 0.0):
            with self.subTest(
                key="productionImplementation", type=type(value).__name__
            ):
                tampered = copy.deepcopy(implementation)
                tampered["productionImplementation"] = value
                with self.assertRaises(SystemExit):
                    check(tampered)

    def test_actual_unit_stage_executes_owner_libraries_and_json_feature_variant(self):
        source = self.authoritative_source()
        body = (
            "run_stage unit_tests "
            + source.split("run_stage unit_tests ", 1)[1].split(
                "\nrun_stage product_integration ", 1
            )[0]
        )
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "commands"
            env = dict(os.environ, OPERATOR_COMMAND_LOG=str(output), EVIDENCE=raw)
            subprocess.run(
                [
                    "bash",
                    "-c",
                    'run_stage() { shift 3; "$@"; }\n'
                    'just() { printf "%s\\n" "$*" >> "$OPERATOR_COMMAND_LOG"; }\n'
                    "export -f just\n" + body,
                ],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            commands = [shlex.split(line) for line in output.read_text().splitlines()]
        expected = {
            "codex-hepta-contracts",
            "codex-hepta-types",
            "codex-hepta-learning-ledger",
            "codex-hepta-learning-artifacts",
            "codex-hepta-intelligence-eval",
            "codex-hepta-intelligence",
        }
        self.assertTrue(
            any(
                expected.issubset(
                    {
                        row[index + 1]
                        for index, value in enumerate(row[:-1])
                        if value == "-p"
                    }
                )
                and "--lib" in row
                for row in commands
            )
        )
        self.assertTrue(
            any(
                "learning_operator_protocol::tests" in row
                and "serde_json/preserve_order,serde_json/arbitrary_precision,serde_json/raw_value"
                in row
                for row in commands
            )
        )
        self.assertTrue(any("learning_operator_" in row for row in commands))
        self.assertTrue(
            any("intelligence_product::evaluation_tests" in row for row in commands)
        )
        for selector in ("plasticity_runtime::", "plasticity_process_bootstrap::"):
            self.assertTrue(
                any(
                    selector in row
                    and "codex-hepta-agentd" in row
                    and "--lib" in row
                    and "--no-tests=fail" in row
                    for row in commands
                )
            )

    def test_actual_product_stage_executes_daemon_process_tests(self):
        source = self.authoritative_source()
        body = (
            "run_stage product_integration "
            + source.split("run_stage product_integration ", 1)[1].split(
                "\nrun_stage mutation ", 1
            )[0]
        )
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "commands"
            subprocess.run(
                [
                    "bash",
                    "-c",
                    'run_stage() { shift 3; "$@"; }\n'
                    'just() { printf "%s\\n" "$*" >> "$OPERATOR_COMMAND_LOG"; }\n'
                    "export -f just\n" + body,
                ],
                env=dict(os.environ, OPERATOR_COMMAND_LOG=str(output), EVIDENCE=raw),
                check=True,
                capture_output=True,
                text=True,
            )
            commands = [shlex.split(line) for line in output.read_text().splitlines()]
        self.assertTrue(
            any(
                all(
                    token in row
                    for token in (
                        "codex-hepta-agentd",
                        "qualification-cognitive-write",
                        "--test",
                        "plasticity_process_e2e",
                        "--no-tests=fail",
                    )
                )
                for row in commands
            )
        )

    def test_synthetic_stage_resolves_merged_v8_and_executes_host_tests(self):
        function = re.search(
            r"(?ms)^qualify_synthetic_merge\(\) \(\n.*?^\)",
            self.authoritative_source(),
        ).group()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "merge").mkdir()
            (root / "evidence").mkdir()
            output = root / "commands"
            subprocess.run(
                [
                    "bash",
                    "-c",
                    'set -e\ngit() { if [[ "$1 ${2:-}" == "worktree add" ]]; then mkdir -p "$SYNTH_DIR"; fi; printf "fixture\\n"; }\n'
                    "cargo() { return 0; }\n"
                    'just() { test "${RUSTY_V8_ARCHIVE:-}" = /fixture/merged-v8.a '
                    '&& test "${RUSTY_V8_SRC_BINDING_PATH:-}" = /fixture/merged-binding.rs '
                    '|| return 32; printf "%s\\n" "$*" >> "$OPERATOR_COMMAND_LOG"; }\n'
                    'python3() { if [[ "$1" == scripts/hepta_ci_v8.py ]]; then '
                    'test "$CODEX_REPO_ROOT" = "$PWD" && test "$PYTHONPATH" = scripts '
                    '&& test -z "${RUSTY_V8_ARCHIVE:-}" && test -z "${RUSTY_V8_SRC_BINDING_PATH:-}" '
                    "|| return 31; "
                    'printf "RUSTY_V8_ARCHIVE=/fixture/merged-v8.a\\nRUSTY_V8_SRC_BINDING_PATH=/fixture/merged-binding.rs\\n" '
                    '> "$GITHUB_ENV"; fi; }\n'
                    + function
                    + "\nqualify_synthetic_merge\n"
                    + 'test "$(cat "$SYNTH_DIR/.hepta-evidence/learning-operator-synthetic-v8.env")" '
                    + '= "$(printf "RUSTY_V8_ARCHIVE=/fixture/merged-v8.a\\nRUSTY_V8_SRC_BINDING_PATH=/fixture/merged-binding.rs")"\n',
                ],
                env=dict(
                    os.environ,
                    ROOT=raw,
                    SYNTH_DIR=str(root / "merge"),
                    BASE_SHA="fixture",
                    SOURCE_SHA="fixture",
                    EVIDENCE="evidence",
                    OPERATOR_COMMAND_LOG=str(output),
                    RUSTY_V8_ARCHIVE="/fixture/stale-source-v8.a",
                    RUSTY_V8_SRC_BINDING_PATH="/fixture/stale-source-binding.rs",
                ),
                check=True,
                capture_output=True,
                text=True,
            )
            commands = [shlex.split(line) for line in output.read_text().splitlines()]
        for selector in (
            "plasticity_runtime::",
            "plasticity_process_bootstrap::",
            "plasticity_process_e2e",
        ):
            self.assertTrue(
                any(
                    selector in row
                    and "codex-hepta-agentd" in row
                    and "--no-tests=fail" in row
                    for row in commands
                )
            )

    def test_receipt_emit_failure_cannot_be_masked_by_a_successful_verify(self):
        source = self.authoritative_source()
        runner = re.search(r"(?ms)^run_stage\(\) \{\n.*?^\}", source).group()
        receipt = re.search(
            r"(?ms)^emit_qualification_receipt\(\) \(\n.*?^\)", source
        ).group()
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "recorded"
            verified = Path(raw) / "verified"
            log = Path(raw) / "stage.log"
            harness = (
                'record_stage() { printf "%s\\n" "$@" > "$OPERATOR_STAGE_ARGS"; }\n'
                'python3() { if [[ "$2" == emit ]]; then return 23; fi; '
                'printf "verify ran\\n" > "$OPERATOR_VERIFY_MARKER"; return 0; }\n'
                "SOURCE_SHA=source SOURCE_TREE=tree WORKFLOW_PATH=workflow WORKFLOW_BLOB=blob\n"
                "BASE_SHA=base SYNTHETIC_SHA=merge SYNTHETIC_TREE=merged TARGET=fixture\n"
                "EVIDENCE_ARGS=()\n"
                + runner
                + "\n"
                + receipt
                + "\n"
                + 'run_stage exact_source_receipt "$OPERATOR_STAGE_LOG" purpose emit_qualification_receipt\n'
            )
            subprocess.run(
                ["bash", "-c", harness],
                env=dict(
                    os.environ,
                    EVIDENCE=raw,
                    OPERATOR_STAGE_LOG=str(log),
                    OPERATOR_STAGE_ARGS=str(output),
                    OPERATOR_VERIFY_MARKER=str(verified),
                ),
                check=True,
                capture_output=True,
                text=True,
            )
            arguments = output.read_text().splitlines()
            self.assertEqual(arguments[1], "failed")
            self.assertEqual(arguments[3], "emit_qualification_receipt ")
            self.assertEqual(arguments[5], "23")
            self.assertFalse(verified.exists())


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
        # Workspace compilation also reads crates outside the operator map.
        self.write("unmapped_dependency.rs", "committed dependency\n")
        self.write(
            "codex-rs/hepta-bellman-operator/Cargo.toml",
            '[package]\nname = "fixture"\nversion = "0.1.0"\n',
        )
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

    def test_unmapped_tracked_changes_invalidate_current_source_qualification(self):
        for staged in (False, True):
            with self.subTest(staged=staged):
                self.write("unmapped_dependency.rs", "changed after qualification\n")
                if staged:
                    self.git("add", "unmapped_dependency.rs")
                # Recomputing the report cannot bind compiled dependencies to
                # an unchanged HEAD while the actual checkout has changed.
                READINESS.emit(self.readiness_args)
                payload = json.loads(self.output.read_text())
                self.assertFalse(payload["engineeringQualified"])
                self.assertFalse(payload["identity_verified"])
                READINESS.verify_path(self.output)
                with self.assertRaises(ValueError):
                    READINESS.verify_path(self.output, require_qualified=True)
                self.git("restore", "--staged", "--worktree", "unmapped_dependency.rs")

    def test_hidden_index_flags_cannot_preserve_current_source_qualification(self):
        for flag in ("assume-unchanged", "skip-worktree"):
            with self.subTest(flag=flag):
                self.git("update-index", "--" + flag, "unmapped_dependency.rs")
                self.write("unmapped_dependency.rs", "hidden altered dependency\n")
                self.assertEqual(
                    self.git("status", "--porcelain", "--untracked-files=no"), ""
                )
                READINESS.emit(self.readiness_args)
                payload = json.loads(self.output.read_text())
                self.assertFalse(payload["engineeringQualified"])
                self.assertFalse(payload["identity_verified"])
                with self.assertRaises(ValueError):
                    READINESS.verify_path(self.output, require_qualified=True)
                self.git("update-index", "--no-" + flag, "unmapped_dependency.rs")
                self.git("restore", "unmapped_dependency.rs")

    def test_untracked_cargo_inputs_cannot_preserve_current_source_qualification(self):
        for source_path in (
            "codex-rs/hepta-bellman-operator/src/bin/injected.rs",
            "codex-rs/hepta-bellman-operator/build.rs",
            "codex-rs/hepta-bellman-operator/tests/injected.rs",
            "codex-rs/hepta-bellman-operator/.cargo/config.toml",
        ):
            for ignored in (False, True):
                with self.subTest(path=source_path, ignored=ignored):
                    if ignored:
                        (self.root / ".git/info/exclude").write_text(
                            source_path + "\n", encoding="utf-8"
                        )
                    self.write(
                        source_path,
                        '[build]\nrustflags = ["--cfg", "unreviewed"]\n'
                        if source_path.endswith(".toml")
                        else "fn main() {}\n",
                    )
                    self.assertEqual(
                        self.git("status", "--porcelain", "--untracked-files=no"), ""
                    )
                    READINESS.emit(self.readiness_args)
                    payload = json.loads(self.output.read_text())
                    self.assertFalse(payload["engineeringQualified"])
                    self.assertFalse(payload["identity_verified"])
                    self.assertTrue(
                        any(
                            "untracked source/config inputs" in row
                            for row in payload["identity_errors"]
                        )
                    )
                    READINESS.verify_path(self.output)
                    with self.assertRaises(ValueError):
                        READINESS.verify_path(self.output, require_qualified=True)
                    (self.root / source_path).unlink()
                    (self.root / ".git/info/exclude").write_text("", encoding="utf-8")

    def test_generated_evidence_and_target_outputs_do_not_change_source_identity(self):
        for output_path in (
            ".hepta-evidence/generated-consumer/src/main.rs",
            ".hepta-evidence/mutation-runs/config.toml",
            "target/debug/build/generated.rs",
            "codex-rs/target/debug/build/generated.rs",
        ):
            self.write(output_path, "generated output\n")
        READINESS.emit(self.readiness_args)
        self.assertTrue(json.loads(self.output.read_text())["engineeringQualified"])
        READINESS.verify_path(self.output, require_qualified=True)

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

    def test_receipt_rejects_numeric_claims_even_after_aggregate_rehash(self):
        path = self.root / self.receipt_args.output
        original = json.loads(path.read_text())
        RECEIPT.verify(path)
        variants = [("schemaVersion", 3.0)]
        for key, boolean in original["claimBoundary"].items():
            variants.extend([(key, int(boolean)), (key, float(boolean))])
        for key, numeric in variants:
            with self.subTest(field=key, type=type(numeric).__name__):
                tampered = copy.deepcopy(original)
                if key == "schemaVersion":
                    tampered[key] = numeric
                else:
                    tampered["claimBoundary"][key] = numeric
                tampered.pop("aggregateEvidenceSha256")
                tampered["aggregateEvidenceSha256"] = hashlib.sha256(
                    RECEIPT.canonical_bytes(tampered)
                ).hexdigest()
                path.write_text(json.dumps(tampered))
                with self.assertRaisesRegex(
                    ValueError, "schema or module|claim boundary"
                ):
                    RECEIPT.verify(path)


if __name__ == "__main__":
    unittest.main()
