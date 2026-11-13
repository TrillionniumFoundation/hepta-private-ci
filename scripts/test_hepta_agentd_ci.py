"""Executable terminal-gate tests and static workflow dependency regressions.

These exercise the actual shared checker in child Python processes. Workflow
checks cover wiring only, not a GitHub run, Rust build or process qualification.
"""

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
LANES = (
    "derived-projections",
    "owner-formatting",
    "catalog-admission",
    "process-qualification",
)


def job_field(job, name):
    """Read one explicit field at the checked-in job indentation, not a step."""
    fields = re.split(r"(?m)^    (?=[^\s#])", job)[1:]
    values = []
    for field in fields:
        key, separator, value = field.partition(":")
        if separator and key.strip() in (name, f"'{name}'", f'"{name}"'):
            values.append(value)
    if len(values) != 1:
        raise ValueError(f"expected exactly one job-level {name} field")
    return values[0].strip("\n")


def job_needs(job):
    """Parse explicit job IDs in flow/block lists; reject unsupported YAML."""
    # Job IDs contain no '#'. Strip only whitespace-separated YAML comments;
    # a '#' joined to an ID remains part of the token and is rejected below.
    lines = [
        re.sub(r"(?:^|[ \t]+)#.*$", "", line).rstrip()
        for line in job_field(job, "needs").splitlines()
    ]
    lines = [line for line in lines if line.strip()]
    value = "\n".join(lines).strip()
    if value.startswith("[") and value.endswith("]"):
        items = value[1:-1].split(",")
        if not items[-1].strip():
            items.pop()  # YAML permits one trailing comma, not empty members.
    elif value.startswith("-"):
        # Keep the common indentation; nested sequences are not job IDs.
        items = []
        indentation = None
        for line in lines:
            match = re.fullmatch(r"( *)-[ \t]+(.+)", line)
            if match is None or len(match[1]) < 6:
                raise ValueError("invalid block needs sequence")
            if indentation is None:
                indentation = match[1]
            if match[1] != indentation:
                raise ValueError("inconsistent block needs indentation")
            items.append(match[2])
    else:
        items = [value]
    names = []
    identifier = r"[a-zA-Z_][a-zA-Z0-9_-]*"
    for item in items:
        match = re.fullmatch(
            rf"({identifier})|'({identifier})'|\"({identifier})\"", item.strip()
        )
        if match is None:
            raise ValueError("needs must contain only explicit job IDs")
        names.append(next(group for group in match.groups() if group is not None))
    if not names or len(names) != len(set(names)):
        raise ValueError("needs must be nonempty and contain no duplicate job IDs")
    return names


class WorkflowNeedsParsingTests(unittest.TestCase):
    def test_equivalent_single_line_multiline_and_block_sequences(self):
        for value in (
            "[derived-projections, owner-formatting, catalog-admission, process-qualification]",
            "\n      [\n        derived-projections, # required\n        owner-formatting,\n"
            "        'catalog-admission',\n        \"process-qualification\",\n      ]",
            "\n      - derived-projections\n      - owner-formatting\n"
            "      - catalog-admission\n      - process-qualification",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    job_needs(f"    needs: {value}\n    steps: []\n"), list(LANES)
                )

    def test_malformed_or_ambiguous_needs_are_rejected(self):
        for job in (
            "    steps:\n      - needs: [derived-projections]\n",
            "    # needs: [derived-projections]\n",
            "    needs: [derived-projections]\n    'needs': [owner-formatting]\n",
            "    needs: []\n",
            "    needs: [derived-projections, derived-projections]\n",
            "    needs: [derived-projections,, owner-formatting]\n",
            "    needs: [derived-projections] ignored\n",
            "    needs: [derived-projections#not-a-comment]\n",
            "    needs: [derived-projections, [owner-formatting]]\n",
            "    needs: ${{ inputs.needs }}\n",
            "    needs: *shared-needs\n",
            "    needs:\n      - derived-projections\n        - owner-formatting\n",
            "    needs:\n      - derived-projections\n        - owner-formatting\n      - catalog-admission\n",
        ):
            with self.subTest(job=job), self.assertRaises(ValueError):
                job_needs(job)


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


class WorkflowDependencyTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")
        # Job IDs occupy exactly two spaces in this checked-in workflow.
        # This assertion intentionally checks the source graph, not YAML execution.
        parts = re.split(
            r"^  ([a-z][a-z0-9-]*):\s*$", self.text.split("\njobs:\n", 1)[1], flags=re.M
        )
        self.jobs = dict(zip(parts[1::2], parts[2::2]))

    def assert_terminal_dependencies(self, job):
        self.assertEqual(job_field(job, "if").strip(), "${{ always() }}")
        self.assertCountEqual(job_needs(job), LANES)

    def test_behavior_and_format_lanes_have_no_predecessor_gate(self):
        for name in LANES:
            with self.subTest(name=name):
                self.assertNotRegex(
                    self.jobs[name], r"(?m)^    (?:needs|if|continue-on-error):"
                )
        for name in ("catalog-admission", "process-qualification"):
            self.assertNotIn("refresh-derived", self.jobs[name])
            self.assertNotIn("cargo fmt", self.jobs[name])

    def test_terminal_gate_is_always_run_and_binds_all_lanes(self):
        job = self.jobs["qualification-result"]
        self.assert_terminal_dependencies(job)
        expected = re.findall(r"(?m)^          EXPECTED_NEEDS: '([^']+)'$", job)
        self.assertEqual(len(expected), 1)
        self.assertCountEqual(json.loads(expected[0]), LANES)
        self.assertIn("NEEDS: ${{ toJSON(needs) }}", job)
        self.assertNotIn("ALLOWED_SKIPPED", job)
        self.assertIn("python3 .github/scripts/check_ci_results.py", job)
        self.assertNotIn("continue-on-error", self.text)

    def test_terminal_gate_rejects_changed_dependencies_or_condition(self):
        for needs in (
            LANES[:-1],
            LANES + ("unreviewed-lane",),
            LANES + (LANES[0],),
        ):
            job = f"    if: ${{{{ always() }}}}\n    needs: [{', '.join(needs)}]\n"
            with (
                self.subTest(needs=needs),
                self.assertRaises((AssertionError, ValueError)),
            ):
                self.assert_terminal_dependencies(job)
        for condition in ("${{ success() }}", "${{ always() && false }}"):
            job = f"    if: {condition}\n    needs: [{', '.join(LANES)}]\n"
            with self.subTest(condition=condition), self.assertRaises(AssertionError):
                self.assert_terminal_dependencies(job)
        with self.assertRaises(ValueError):
            self.assert_terminal_dependencies(
                f"    needs: [{', '.join(LANES)}]\n"
                "    steps:\n      - if: ${{ always() }}\n"
            )
        with self.assertRaises(ValueError):
            self.assert_terminal_dependencies(
                "    if: ${{ always() }}\n    if: ${{ success() }}\n"
                f"    needs: [{', '.join(LANES)}]\n"
            )

    def test_existing_behavior_suites_remain(self):
        process = self.jobs["process-qualification"]
        for target in (
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
                self.assertIn(target, process)
        self.assertIn("just test --locked", self.jobs["catalog-admission"])
        self.assertIn("refresh-derived --check", self.jobs["derived-projections"])
        self.assertIn("cargo fmt", self.jobs["owner-formatting"])
        self.assertIn("-- --check", self.jobs["owner-formatting"])

    def test_checkout_and_candidate_permissions_remain_read_only(self):
        self.assertIn("permissions:\n  contents: read", self.text)
        self.assertNotIn("contents: write", self.text)
        self.assertNotIn("pull_request_target:", self.text)
        self.assertEqual(self.text.count("persist-credentials: false"), len(self.jobs))

    def test_process_matrix_covers_source_and_merge_on_each_platform(self):
        process = self.jobs["process-qualification"]
        self.assertIn('["source-head","merge-candidate"]', process)
        self.assertIn('["ubuntu-24.04","macos-15"]', process)
        self.assertIn("ref: ${{ env.EXPECTED_SHA }}", process)
        self.assertIn("fail-fast: false", process)
        self.assertNotIn("exclude:", process)
        self.assertIn('test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"', process)
        self.assertIn("python3 scripts/hepta_ci_candidate.py", process)
        self.assertIn('--base "$BASE_SHA" --lane base-merge', process)
        self.assertIn("merge-tree --write-tree", process)
        self.assertIn('test "$(git rev-parse HEAD^{tree})" = "$expected_tree"', process)

    def test_native_sharing_is_bound_to_the_existing_planner_and_final_fanin(self):
        process = self.jobs["process-qualification"]
        self.assertIn("id: execution", process)
        self.assertIn('--github-output "$GITHUB_OUTPUT"', process)
        self.assertIn("args+=(--lane source-head)", process)
        self.assertIn("steps.execution.outputs.run_native == 'true'", process)
        terminal = self.jobs["qualification-result"]
        self.assert_terminal_dependencies(terminal)
        self.assertIn(
            "scripts.tests.test_hepta_ci_candidate", self.jobs["derived-projections"]
        )
        self.assertNotIn("continue-on-error", process)

    def test_catalog_and_formatter_use_the_repository_toolchain_directory(self):
        for name in ("owner-formatting", "catalog-admission"):
            with self.subTest(name=name):
                job = self.jobs[name]
                self.assertIn("working-directory: codex-rs", job)
                self.assertNotIn("--manifest-path codex-rs/Cargo.toml", job)
                self.assertIn("--manifest-path Cargo.toml", job)


if __name__ == "__main__":
    unittest.main()
