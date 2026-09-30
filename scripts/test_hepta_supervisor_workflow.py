"""Closed qualification wiring. This does not execute GitHub Actions or Cargo."""

from __future__ import annotations

import ast
from pathlib import Path
import re
import subprocess
import unittest

from scripts.hepta_supervisor_ci_v3 import current_plan

PLAN = current_plan()
BINDING_PATHS = PLAN.binding_paths
PLANS = PLAN.plans
REQUIRED_BINARY_TESTS = PLAN.required_binary_tests

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hepta-supervisor-qualification.yml"


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()

    def test_all_candidate_bound_suites_are_dispatched_exactly_once(self):
        steps = self.text.split("      - name: ")
        names = []
        for step in steps:
            match = re.search(
                r"hepta_supervisor_ci_v3\.py execute ([a-z0-9-]+) --records", step
            )
            if match:
                names.append(match[1])
                self.assertIn(
                    "if: ${{ !cancelled() && steps.ready.outcome == 'success' }}", step
                )
                self.assertNotIn("continue-on-error:", step)
        self.assertEqual(set(names), set(PLANS))
        self.assertEqual(len(names), len(PLANS))

    def test_rejection_suites_and_all_evidence_changes_trigger_scope(self):
        for module in (
            "test_hepta_supervisor_ci",
            "test_hepta_supervisor_evidence",
            "test_hepta_supervisor_workflow",
            "test_hepta_supervisor_status",
            "test_hepta_supervisor_external_receipt",
            "test_hepta_supervisor_ci_v3",
            "test_runtime_supervisor_materialize",
        ):
            self.assertIn(f"scripts.{module}", self.text)
        for path in (
            "scripts/hepta_supervisor_ci.py",
            "scripts/hepta_supervisor_ci_v3.py",
            "scripts/hepta_supervisor_evidence.py",
            "scripts/hepta_supervisor_status.py",
            "scripts/hepta_supervisor_external_receipt.py",
            "scripts/hepta_supervisor_artifact_gate.py",
            "scripts/test_hepta_supervisor_ci.py",
            "scripts/test_hepta_supervisor_ci_v3.py",
            "scripts/test_hepta_supervisor_evidence.py",
            "scripts/test_hepta_supervisor_workflow.py",
            "scripts/test_hepta_supervisor_status.py",
            "scripts/test_hepta_supervisor_external_receipt.py",
            "scripts/runtime_supervisor_six_phase_materialize.py",
            "scripts/runtime_supervisor_six_phase_followup.py",
            "scripts/test_runtime_supervisor_materialize.py",
        ):
            self.assertIn(f'"{path}"', self.text)
            self.assertIn(path, BINDING_PATHS)
        self.assertIn('p.startswith("docs/modules/runtime.supervisor/")', self.text)

    def test_four_pr_lanes_exact_checkout_and_real_main_rerun_are_retained(self):
        self.assertIn("push:\n    branches: [main]", self.text)
        self.assertIn("os: [ubuntu-24.04, macos-15]", self.text)
        self.assertIn('["source-head","base-merge"]', self.text)
        self.assertIn("ref: ${{ env.SOURCE_SHA }}", self.text)
        self.assertIn("uses: ./.github/actions/hepta-synthetic-merge", self.text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$CANDIDATE"', self.text)
        self.assertIn("nextest@0.9.103", self.text)

    def test_default_authority_denial_uses_only_the_pinned_bundle(self):
        command = PLANS["default-products"][1]
        self.assertIn("--no-default-features", command)
        self.assertNotIn("--features", command)
        source = (
            ROOT / "codex-rs/hepta-supervisor/tests/default_authority_denied.rs"
        ).read_text()
        self.assertIn(
            '#![cfg(all(unix, not(feature = "production-authority")))]', source
        )
        self.assertIn('env!("CARGO_BIN_EXE_hepta-supervisord")', source)
        self.assertIn(
            "Err(SupervisorError::ProductionAuthorityFeatureDisabled)", source
        )
        self.assertIn('"--authority-bundle"', source)
        self.assertNotIn('"--grant-verifier-key"', source)
        for name in REQUIRED_BINARY_TESTS["default-products"][
            "codex-hepta-supervisor::default_authority_denied"
        ]:
            self.assertRegex(source, rf"\bfn {re.escape(name)}\(")

    def test_receipt_requires_every_suite_and_preserves_negative_release_claims(self):
        source = (ROOT / "scripts/hepta_supervisor_ci.py").read_text()
        tree = ast.parse(source)
        receipts = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Dict)
            and any(
                isinstance(key, ast.Constant) and key.value == "qualification_scope"
                for key in node.keys
                if key is not None
            )
        ]
        self.assertEqual(len(receipts), 1)
        values = {
            key.value: value
            for key, value in zip(receipts[0].keys, receipts[0].values)
            if isinstance(key, ast.Constant)
        }
        for name in (
            "deployment_qualification_complete",
            "independent_acceptance_complete",
            "production_activation",
            "release",
        ):
            self.assertIsInstance(values[name], ast.Constant)
            self.assertIs(values[name].value, False)
        self.assertIn('{f"{name}.json" for name in PLANS}', source)
        self.assertIn(
            'git_identity["parents"] == [context["base_sha"], context["source_sha"]]',
            source,
        )
        merge_commands = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.List)
            and len(node.elts) >= 3
            and all(isinstance(item, ast.Constant) for item in node.elts[:3])
            and [item.value for item in node.elts[:3]]
            == ["git", "merge-tree", "--write-tree"]
        ]
        self.assertEqual(len(merge_commands), 1)
        command = merge_commands[0]
        self.assertEqual(len(command.elts), 5)
        for argument, field in zip(command.elts[3:], ("base_sha", "source_sha")):
            self.assertIsInstance(argument, ast.Subscript)
            self.assertIsInstance(argument.value, ast.Name)
            self.assertEqual(argument.value.id, "context")
            self.assertEqual(ast.literal_eval(argument.slice), field)

    def test_fan_in_rejects_every_applicable_non_success_state(self):
        block = self.text.split("  qualification-result:\n", 1)[1]
        self.assertIn("if: ${{ always() }}", block)
        script = block.split("        run: |\n", 1)[1]
        script = "\n".join(line[10:] for line in script.splitlines())
        for scope in ("success", "failure", "skipped", "cancelled", ""):
            for required in ("true", "false", "", "unexpected"):
                for result in ("success", "failure", "skipped", "cancelled", ""):
                    expected = scope == "success" and (
                        (required == "true" and result == "success")
                        or (required == "false" and result == "skipped")
                    )
                    run = subprocess.run(
                        ["bash", "-c", script],
                        env={
                            "SCOPE_RESULT": scope,
                            "REQUIRED": required,
                            "RESULT": result,
                        },
                        capture_output=True,
                        timeout=5,
                        check=False,
                    )
                    with self.subTest(scope=scope, required=required, result=result):
                        self.assertEqual(run.returncode == 0, expected)

    def test_evidence_is_retained_even_when_a_suite_fails(self):
        retention = self.text.split(
            "      - name: Retain raw execution evidence even on failure", 1
        )[1]
        self.assertIn("if: always()", retention)
        self.assertIn("if-no-files-found: error", retention)
        self.assertNotIn("continue-on-error:", self.text)
        self.assertIn(
            '--output "$RUNNER_TEMP/hepta-supervisor/qualification.json"', self.text
        )

    def test_operator_target_receipt_is_bound_to_actual_current_run(self):
        text = (
            ROOT / ".github/workflows/runtime-supervisor-target-host-qualification.yml"
        ).read_text()
        execution = text.split(
            "      - name: Execute complete operator target-host fault matrix", 1
        )[1]
        execution = execution.split("      - name: Retain target-host evidence", 1)[0]
        for field in (
            "LANE",
            "SOURCE_SHA",
            "BASE_SHA",
            "MERGE_CANDIDATE_SHA",
            "TESTED_SHA",
            "FINAL_MERGE_SHA",
            "TARGET_OS",
        ):
            self.assertIn(f"          {field}:", execution)
        self.assertIn("--bind-current-run", execution)
        self.assertIn('--workflow-run-attempt "$GITHUB_RUN_ATTEMPT"', execution)
        self.assertIn("TARGET_BINARY_SHA256=%s", text)
        self.assertIn(
            '--binary "$HEPTA_VERIFIER_TARGET_DIR/release/hepta-supervisord"', execution
        )


if __name__ == "__main__":
    unittest.main()
