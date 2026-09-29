"""Executable terminal-gate tests and static workflow dependency regressions.

These exercise the actual shared checker in child Python processes. Workflow
checks cover wiring only, not a GitHub run, Rust build or process qualification.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from scripts.hepta_workflow_commands import load_workflow
from scripts.hepta_workflow_commands import run_scalar_commands
from scripts.hepta_workflow_commands import workflow_events
from scripts.hepta_workflow_commands import workflow_expression_references
from scripts.hepta_workflow_commands import workflow_literal_collection_values

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / ".github/scripts/check_ci_results.py"
WORKFLOW = ROOT / ".github/workflows/hepta-gap-agentd-process.yml"
LANES = (
    "derived-projections",
    "owner-formatting",
    "catalog-admission",
    "process-qualification",
)


class TerminalGateTests(unittest.TestCase):
    def run_gate(self, needs, *, expected=LANES, allowed=()):
        env = os.environ.copy()
        env["NEEDS"] = json.dumps(needs)
        env["ALLOWED_SKIPPED"] = json.dumps(allowed)
        env.pop("EXPECTED_NEEDS", None)
        if expected is not None:
            env["EXPECTED_NEEDS"] = json.dumps(expected)
        return subprocess.run(
            [sys.executable, str(CHECKER)],
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )

    def success(self):
        return {name: {"result": "success", "outputs": {}} for name in LANES}

    def test_all_lanes_succeed(self):
        self.assertEqual(self.run_gate(self.success()).returncode, 0)

    def test_every_non_success_lane_is_blocking(self):
        for name in LANES:
            for result in ("failure", "cancelled", "skipped"):
                with self.subTest(name=name, result=result):
                    needs = self.success()
                    needs[name]["result"] = result
                    self.assertNotEqual(self.run_gate(needs).returncode, 0)

    def test_empty_needs_never_passes(self):
        for expected in (None, (), LANES):
            with self.subTest(expected=expected):
                self.assertNotEqual(self.run_gate({}, expected=expected).returncode, 0)

    def test_missing_and_extra_jobs_rejected(self):
        missing = self.success()
        del missing["derived-projections"]
        extra = self.success()
        extra["unreviewed-lane"] = {"result": "success"}
        for needs in (missing, extra):
            self.assertNotEqual(self.run_gate(needs).returncode, 0)

    def test_malformed_results_rejected(self):
        for result in ({}, None, "success", {"result": True}, {"result": "neutral"}):
            with self.subTest(result=result):
                needs = self.success()
                needs["derived-projections"] = result
                self.assertNotEqual(self.run_gate(needs).returncode, 0)

    def test_existing_explicit_scope_exception_is_preserved(self):
        needs = {"scope": {"result": "success"}, "unused": {"result": "skipped"}}
        self.assertEqual(
            self.run_gate(needs, expected=None, allowed=["unused"]).returncode, 0
        )
        for result in ("failure", "cancelled"):
            needs["unused"]["result"] = result
            self.assertNotEqual(
                self.run_gate(needs, expected=None, allowed=["unused"]).returncode, 0
            )

    def test_unknown_or_malformed_scope_exceptions_rejected(self):
        for allowed in (
            ["absent"],
            "catalog-admission",
            [True],
            ["catalog-admission"] * 2,
        ):
            with self.subTest(allowed=allowed):
                self.assertNotEqual(
                    self.run_gate(self.success(), allowed=allowed).returncode, 0
                )

    def test_malformed_expected_set_rejected(self):
        for expected in ([], "catalog-admission", [True], list(LANES) + [LANES[0]]):
            with self.subTest(expected=expected):
                self.assertNotEqual(
                    self.run_gate(self.success(), expected=expected).returncode, 0
                )


def command_lines(job: dict) -> list[str]:
    return [
        " ".join(command)
        for step in job.get("steps", [])
        for command in run_scalar_commands(step.get("run", ""))
    ]


def contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(contains_key(item, key) for item in value)
    return False


def needs(job: dict) -> set[str]:
    value = job.get("needs", [])
    return {value} if isinstance(value, str) else set(value)


def condition_body(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if value.startswith("${{") and value.endswith("}}"):
        value = value[3:-2]
    return "".join(value.split())


class WorkflowDependencyTests(unittest.TestCase):
    def setUp(self):
        self.workflow = load_workflow(WORKFLOW.read_text(encoding="utf-8"))
        self.jobs = self.workflow["jobs"]

    def test_behavior_and_format_lanes_have_no_predecessor_gate(self):
        for name in LANES:
            with self.subTest(name=name):
                job = self.jobs[name]
                self.assertFalse({"needs", "if", "continue-on-error"} & set(job))
        for name in ("catalog-admission", "process-qualification"):
            lines = command_lines(self.jobs[name])
            self.assertFalse(any("refresh-derived" in line for line in lines))
            self.assertFalse(any("cargo fmt" in line for line in lines))

    def test_terminal_gate_is_always_run_and_binds_all_lanes(self):
        job = self.jobs["qualification-result"]
        self.assertEqual(condition_body(job.get("if")), "always()")
        self.assertEqual(needs(job), set(LANES))
        gate_steps = [
            step
            for step in job["steps"]
            if any(
                ".github/scripts/check_ci_results.py" in line
                for line in [
                    " ".join(command)
                    for command in run_scalar_commands(step.get("run", ""))
                ]
            )
        ]
        self.assertEqual(len(gate_steps), 1)
        environment = gate_steps[0].get("env", {})
        self.assertEqual(set(json.loads(environment["EXPECTED_NEEDS"])), set(LANES))
        self.assertNotIn("ALLOWED_SKIPPED", environment)
        self.assertIn("needs", workflow_expression_references(environment["NEEDS"]))
        self.assertFalse(contains_key(self.workflow, "continue-on-error"))

    def test_existing_behavior_suites_remain(self):
        process = command_lines(self.jobs["process-qualification"])
        for target in (
            "--cargo-profile dev-small -p codex-hepta-supervisor",
            "--test paired_process_product --retries 0 --test-threads=1",
            "optional_module_restart",
            "runtime_shutdown_outcomes",
            "retirement_recovery",
            "operation_timer_fence",
            "destination_recovery_binding",
            "cognitive_product_e2e",
            "runtime::tests::qualification_",
            "cargo clippy --locked",
        ):
            with self.subTest(target=target):
                self.assertTrue(any(target in line for line in process))
        self.assertTrue(
            any(
                "just test --locked" in line
                for line in command_lines(self.jobs["catalog-admission"])
            )
        )
        self.assertTrue(
            any(
                "refresh-derived --check" in line
                for line in command_lines(self.jobs["derived-projections"])
            )
        )
        formatting = command_lines(self.jobs["owner-formatting"])
        self.assertTrue(
            any("cargo fmt" in line and "-- --check" in line for line in formatting)
        )

    def test_checkout_and_candidate_permissions_remain_read_only(self):
        self.assertEqual(self.workflow.get("permissions"), {"contents": "read"})
        self.assertNotIn("pull_request_target", workflow_events(self.workflow))
        for name, job in self.jobs.items():
            checkouts = [
                step
                for step in job.get("steps", [])
                if str(step.get("uses", "")).startswith("actions/checkout@")
            ]
            self.assertEqual(len(checkouts), 1, name)
            self.assertEqual(
                checkouts[0].get("with", {}).get("persist-credentials"), "false"
            )
        self.assertFalse(
            any(
                value == "write"
                for value in self.workflow.get("permissions", {}).values()
            )
        )

    def test_process_matrix_covers_source_and_merge_on_each_platform(self):
        job = self.jobs["process-qualification"]
        strategy = job["strategy"]
        self.assertEqual(strategy.get("fail-fast"), "false")
        self.assertNotIn("exclude", strategy["matrix"])
        self.assertEqual(
            workflow_literal_collection_values(strategy["matrix"]["lane"]),
            {"source-head", "merge-candidate"},
        )
        self.assertEqual(
            workflow_literal_collection_values(strategy["matrix"]["os"]),
            {"ubuntu-24.04", "macos-15"},
        )
        checkout = next(
            step
            for step in job["steps"]
            if str(step.get("uses", "")).startswith("actions/checkout@")
        )
        self.assertEqual(
            workflow_expression_references(checkout["with"]["ref"]),
            {"env.EXPECTED_SHA"},
        )
        lines = command_lines(job)
        for expected in (
            "test $(git rev-parse HEAD) = $EXPECTED_SHA",
            "python3 scripts/hepta_ci_candidate.py",
            "--base $BASE_SHA --lane base-merge",
            "git merge-tree --write-tree $BASE_SHA $SOURCE_SHA",
            "test $(git rev-parse HEAD^{tree}) = $expected_tree",
        ):
            with self.subTest(expected=expected):
                self.assertTrue(any(expected in line for line in lines))

    def test_native_sharing_is_bound_to_existing_planner_and_final_fanin(self):
        process = self.jobs["process-qualification"]
        execution = [step for step in process["steps"] if step.get("id") == "execution"]
        self.assertEqual(len(execution), 1)
        lines = [
            " ".join(command)
            for command in run_scalar_commands(execution[0].get("run", ""))
        ]
        self.assertTrue(any("--github-output $GITHUB_OUTPUT" in line for line in lines))
        self.assertTrue(any("--lane source-head" in line for line in lines))
        guarded = [
            step
            for step in process["steps"]
            if "steps.execution.outputs.run_native"
            in workflow_expression_references(step.get("if", ""), implicit=True)
        ]
        self.assertGreaterEqual(len(guarded), 1)
        self.assertIn("process-qualification", needs(self.jobs["qualification-result"]))
        self.assertTrue(
            any(
                "scripts.tests.test_hepta_ci_candidate" in line
                for line in command_lines(self.jobs["derived-projections"])
            )
        )
        self.assertFalse(contains_key(process, "continue-on-error"))

    def test_catalog_and_formatter_use_repository_toolchain_directory(self):
        for name in ("owner-formatting", "catalog-admission"):
            with self.subTest(name=name):
                job = self.jobs[name]
                executable = [step for step in job["steps"] if step.get("run")]
                self.assertTrue(executable)
                self.assertTrue(
                    all(
                        step.get("working-directory") == "codex-rs"
                        for step in executable
                    )
                )
                lines = command_lines(job)
                self.assertTrue(
                    any("--manifest-path Cargo.toml" in line for line in lines)
                )
                self.assertFalse(
                    any("--manifest-path codex-rs/Cargo.toml" in line for line in lines)
                )


if __name__ == "__main__":
    unittest.main()
