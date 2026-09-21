"""Executable terminal-gate tests and static workflow dependency regressions.

These exercise the actual shared checker in child Python processes. Workflow
checks cover wiring only, not a GitHub run, Rust build or process qualification.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / ".github/scripts/check_ci_results.py"
WORKFLOW = ROOT / ".github/workflows/hepta-gap-agentd-process.yml"
LANES = ("derived-projections", "owner-formatting", "catalog-admission", "process-qualification")


class TerminalGateTests(unittest.TestCase):
    def run_gate(self, needs, *, expected=LANES, allowed=()):
        env = os.environ.copy()
        env["NEEDS"] = json.dumps(needs)
        env["ALLOWED_SKIPPED"] = json.dumps(allowed)
        env.pop("EXPECTED_NEEDS", None)
        if expected is not None:
            env["EXPECTED_NEEDS"] = json.dumps(expected)
        return subprocess.run(
            [sys.executable, str(CHECKER)], env=env, text=True,
            capture_output=True, timeout=10, check=False,
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
        self.assertEqual(self.run_gate(needs, expected=None, allowed=["unused"]).returncode, 0)
        for result in ("failure", "cancelled"):
            needs["unused"]["result"] = result
            self.assertNotEqual(self.run_gate(needs, expected=None, allowed=["unused"]).returncode, 0)

    def test_unknown_or_malformed_scope_exceptions_rejected(self):
        for allowed in (["absent"], "catalog-admission", [True], ["catalog-admission"] * 2):
            with self.subTest(allowed=allowed):
                self.assertNotEqual(self.run_gate(self.success(), allowed=allowed).returncode, 0)

    def test_malformed_expected_set_rejected(self):
        for expected in ([], "catalog-admission", [True], list(LANES) + [LANES[0]]):
            with self.subTest(expected=expected):
                self.assertNotEqual(self.run_gate(self.success(), expected=expected).returncode, 0)


class WorkflowDependencyTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")
        # Job IDs occupy exactly two spaces in this checked-in workflow.
        # This assertion intentionally checks the source graph, not YAML execution.
        parts = re.split(r"^  ([a-z][a-z0-9-]*):\s*$", self.text.split("\njobs:\n", 1)[1], flags=re.M)
        self.jobs = dict(zip(parts[1::2], parts[2::2]))

    def test_behavior_and_format_lanes_have_no_predecessor_gate(self):
        for name in LANES:
            with self.subTest(name=name):
                self.assertNotRegex(self.jobs[name], r"(?m)^    (?:needs|if|continue-on-error):")
        for name in ("catalog-admission", "process-qualification"):
            self.assertNotIn("refresh-derived", self.jobs[name])
            self.assertNotIn("cargo fmt", self.jobs[name])

    def test_terminal_gate_is_always_run_and_binds_all_lanes(self):
        job = self.jobs["qualification-result"]
        self.assertIn("if: ${{ always() }}", job)
        matched = re.search(r"(?m)^    needs: \[([^\]]+)\]$", job)
        self.assertIsNotNone(matched)
        self.assertEqual({name.strip() for name in matched.group(1).split(",")}, set(LANES))
        self.assertIn("EXPECTED_NEEDS:", job)
        self.assertNotIn("ALLOWED_SKIPPED", job)
        self.assertIn("python3 .github/scripts/check_ci_results.py", job)
        self.assertNotIn("continue-on-error", self.text)

    def test_existing_behavior_suites_remain(self):
        process = self.jobs["process-qualification"]
        for target in ("optional_module_restart", "runtime_shutdown_outcomes", "retirement_recovery", "operation_timer_fence", "destination_recovery_binding", "cognitive_product_e2e", "runtime::tests::qualification_", "cargo clippy --locked"):
            with self.subTest(target=target):
                self.assertIn(target, process)
        self.assertIn("cargo test --locked", self.jobs["catalog-admission"])
        self.assertIn("refresh-derived --check", self.jobs["derived-projections"])
        self.assertIn("cargo fmt", self.jobs["owner-formatting"])
        self.assertIn("-- --check", self.jobs["owner-formatting"])

    def test_checkout_and_candidate_permissions_remain_read_only(self):
        self.assertIn("permissions:\n  contents: read", self.text)
        self.assertNotIn("contents: write", self.text)
        self.assertNotIn("pull_request_target:", self.text)
        self.assertEqual(self.text.count("persist-credentials: false"), len(self.jobs))


if __name__ == "__main__":
    unittest.main()
