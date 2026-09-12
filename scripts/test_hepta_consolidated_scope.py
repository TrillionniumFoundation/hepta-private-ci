"""Execute the consolidated workflow's change-scope decision in real Git repos."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def workflow_script(marker):
    workflow = (ROOT / ".github/workflows/hepta-consolidated-source.yml").read_text()
    block = workflow.split(marker + "\n", 1)[1].split("        run: |\n", 1)[1]
    lines = []
    for line in block.splitlines():
        if line and not line.startswith("          "):
            break
        lines.append(line[10:])
    return "\n".join(lines)


class ConsolidatedScopeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hepta-ci-scope-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        # Execute the actual run block, not a reimplementation of its decision.
        self.script = workflow_script("        id: scope")
        self.git("init", "-q")
        self.git("config", "user.name", "scope-test")
        self.git("config", "user.email", "scope-test@example.invalid")
        (self.root / "readme").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], text=True, stderr=subprocess.PIPE
        ).strip()

    def scope(self, base, source):
        # Keep GITHUB_OUTPUT outside the fixture repository and start it empty.
        with tempfile.TemporaryDirectory(prefix="hepta-ci-output-") as directory:
            output = Path(directory) / "output"
            result = subprocess.run(
                ["bash", "-c", self.script],
                cwd=self.root,
                env={
                    **os.environ,
                    "BASE_SHA": base,
                    "SOURCE_SHA": source,
                    "GITHUB_OUTPUT": str(output),
                },
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result, output.read_text() if output.exists() else ""

    def test_only_unchanged_shared_core_can_skip_full_regression(self):
        (self.root / "readme").write_text("documentation change\n")
        self.git("commit", "-qam", "docs")
        source = self.git("rev-parse", "HEAD")
        result, output = self.scope(self.base, source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, "required=false\n")
        for path in ("codex-rs/core/x", "codex-rs/common/x", "codex-rs/protocol/x"):
            with self.subTest(path=path):
                before = self.git("rev-parse", "HEAD")
                target = self.root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("shared change\n")
                self.git("add", ".")
                self.git("commit", "-qm", "shared change")
                result, output = self.scope(before, self.git("rev-parse", "HEAD"))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output, "required=true\n")

    def test_missing_base_runs_full_regression_instead_of_skipping(self):
        for base in ("", "0" * 40, "f" * 40):
            with self.subTest(base=base):
                result, output = self.scope(base, self.base)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output, "required=true\n")

    def test_wrong_checkout_cannot_publish_a_scope_decision(self):
        (self.root / "readme").write_text("new source\n")
        self.git("commit", "-qam", "new source")
        source = self.git("rev-parse", "HEAD")
        self.git("checkout", "--detach", self.base)
        result, output = self.scope(self.base, source)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output, "")

    def test_shared_build_inputs_cannot_skip_full_regression(self):
        for path in (
            "codex-rs/Cargo.toml", "codex-rs/Cargo.lock",
            "codex-rs/another-crate/Cargo.toml", "codex-rs/another-crate/build.rs",
            "codex-rs/.cargo/config.toml", ".cargo/config.toml",
            "codex-rs/rust-toolchain.toml", "rust-toolchain.toml",
            "justfile", "scripts/hepta_ci_v8.py",
            ".github/workflows/hepta-consolidated-source.yml",
        ):
            with self.subTest(path=path):
                before = self.git("rev-parse", "HEAD")
                target = self.root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("build input changed\n")
                self.git("add", ".")
                self.git("commit", "-qm", "build input")
                result, output = self.scope(before, self.git("rev-parse", "HEAD"))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output, "required=true\n")

    def test_dirty_tracked_content_cannot_claim_exact_source(self):
        for staged in (False, True):
            with self.subTest(staged=staged):
                self.git("reset", "--hard", self.base)
                (self.root / "readme").write_text("not the committed source\n")
                if staged:
                    self.git("add", "readme")
                result, output = self.scope(self.base, self.base)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(output, "")

    def test_deleting_shared_build_input_requires_regression(self):
        lock = self.root / "codex-rs/Cargo.lock"
        lock.parent.mkdir()
        lock.write_text("lock data\n")
        self.git("add", ".")
        self.git("commit", "-qm", "lock")
        before = self.git("rev-parse", "HEAD")
        self.git("rm", "codex-rs/Cargo.lock")
        self.git("commit", "-qm", "remove lock")
        result, output = self.scope(before, self.git("rev-parse", "HEAD"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, "required=true\n")

    def test_module_documentation_does_not_force_workspace_rebuild(self):
        path = self.root / "codex-rs/some-crate/TECHNICAL.md"
        path.parent.mkdir(parents=True)
        path.write_text("documentation only\n")
        self.git("add", ".")
        self.git("commit", "-qm", "module docs")
        result, output = self.scope(self.base, self.git("rev-parse", "HEAD"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, "required=false\n")


class ConsolidatedExecutionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hepta-ci-execution-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.calls = self.root / "calls.jsonl"
        for command in ("just", "cargo"):
            path = self.root / command
            path.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "name = Path(sys.argv[0]).name\n"
                "with open(os.environ['CALL_LOG'], 'a') as log:\n"
                "    log.write(json.dumps([name, *sys.argv[1:]]) + '\\n')\n"
                "sys.exit(int(os.environ.get('FAKE_' + name.upper() + '_STATUS', '0')))\n"
            )
            path.chmod(0o755)

    def execute(self, marker, **environment):
        self.calls.unlink(missing_ok=True)
        return subprocess.run(
            ["bash", "-c", workflow_script(marker)],
            cwd=self.root,
            env={
                **os.environ,
                "PATH": str(self.root) + os.pathsep + os.environ["PATH"],
                "CALL_LOG": str(self.calls),
                "PACKAGES": "codex-first codex-second",
                "RUNNER_TEMP": str(self.root),
                "LANE": "source-head",
                **environment,
            },
            capture_output=True, text=True, timeout=10,
        )

    def invocations(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def test_each_source_and_merge_lane_runs_one_correct_test_target(self):
        marker = "      - name: Compile and test actual imported packages"
        for lane in ("source-head", "base-merge"):
            for full in ("true", "false"):
                with self.subTest(lane=lane, full=full):
                    result = self.execute(marker, FULL_WORKSPACE=full, LANE=lane)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    tests = [call for call in self.invocations() if call[0] == "just"]
                    expected = ["just", "test", "--locked"]
                    if full == "false":
                        expected += ["-p", "codex-first", "-p", "codex-second"]
                    self.assertEqual(tests, [expected])

    def test_unknown_scope_cannot_silently_run_a_smaller_suite(self):
        marker = "      - name: Compile and test actual imported packages"
        for value in ("", "TRUE", "unknown"):
            with self.subTest(value=value):
                result = self.execute(marker, FULL_WORKSPACE=value)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.invocations(), [])

    def test_test_command_failure_is_not_hidden_by_log_capture(self):
        result = self.execute(
            "      - name: Compile and test actual imported packages",
            FULL_WORKSPACE="true", FAKE_JUST_STATUS="23",
        )
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(self.invocations(), [["just", "test", "--locked"]])

    def test_aggregate_gate_rejects_failed_cancelled_or_skipped_dependencies(self):
        marker = "      - name: Require completed source and merge qualification"
        for scope in ("success", "failure", "cancelled", "skipped"):
            for result in ("success", "failure", "cancelled", "skipped"):
                with self.subTest(scope=scope, result=result):
                    observed = self.execute(
                        marker, SCOPE_RESULT=scope, FULL_WORKSPACE="true",
                        QUALIFICATION_RESULT=result,
                    )
                    self.assertEqual(observed.returncode == 0, scope == result == "success")
        for full in ("false", "", "unknown"):
            with self.subTest(full=full):
                observed = self.execute(
                    marker, SCOPE_RESULT="success", FULL_WORKSPACE=full,
                    QUALIFICATION_RESULT="success",
                )
                self.assertEqual(observed.returncode == 0, full == "false")

    def test_lint_stays_strict_and_propagates_failure(self):
        expected = ["cargo", "clippy", "--locked", "-p", "codex-first", "-p", "codex-second", "--all-targets", "--", "-D", "warnings"]
        for status in ("0", "31"):
            with self.subTest(status=status):
                result = self.execute("      - name: Strict owner lint", FAKE_CARGO_STATUS=status)
                self.assertEqual(result.returncode, int(status), result.stderr)
                self.assertEqual(self.invocations(), [expected])


class ConsolidatedRecordTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hepta-ci-record-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "record-test")
        self.git("config", "user.email", "record-test@example.invalid")
        (self.root / "input").write_text("base\n")
        self.git("add", "input")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        (self.root / "input").write_text("source\n")
        self.git("commit", "-qam", "source")
        self.source = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True, stderr=subprocess.PIPE).strip()

    def record(self, **override):
        env = {
            **os.environ,
            "SOURCE_SHA": self.source, "BASE_SHA": self.base,
            "EXPECTED_TESTED_SHA": self.source, "FULL_WORKSPACE": "false",
            "PACKAGES": "codex-first codex-second", "LANE": "source-head",
            "TEST_OUTCOME": "success", "LINT_OUTCOME": "success", "FORMAT_OUTCOME": "success",
            "PRIOR_STATUS": "success", "RUNNER_TEMP": str(self.root.parent),
            "GITHUB_STEP_SUMMARY": str(self.root.parent / "summary"),
            **override,
        }
        result = subprocess.run(
            ["bash", "-c", workflow_script("      - name: Record exact tested identity and phase results")],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=10,
        )
        path = self.root.parent / ("hepta-qualification-" + env["LANE"]) / "result.json"
        return result, json.loads(path.read_text())

    def test_source_record_binds_actual_tree_targets_and_nonpassing_outcomes(self):
        result, record = self.record(TEST_OUTCOME="failure", LINT_OUTCOME="skipped", PRIOR_STATUS="failure")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(record["identity_valid"])
        self.assertEqual(record["tested_sha"], self.source)
        self.assertEqual(record["tested_tree"], self.git("rev-parse", "HEAD^{tree}"))
        self.assertEqual(record["parents"], [self.base])
        self.assertEqual(record["test_command"], ["just", "test", "--locked", "-p", "codex-first", "-p", "codex-second"])
        self.assertEqual(record["outcomes"], {"tests": "failure", "clippy": "skipped", "format": "success"})
        self.assertEqual(record["prior_job_status"], "failure")

    def test_merge_record_requires_exact_ordered_parents(self):
        # Only test identity recording here; merge construction remains owned by
        # the existing shared action, not by this fixture.
        tree = self.git("rev-parse", "HEAD^{tree}")
        for parents in ((self.base, self.source), (self.source, self.base)):
            with self.subTest(parents=parents):
                merge = self.git("commit-tree", tree, "-p", parents[0], "-p", parents[1], "-m", "fixture merge")
                self.git("checkout", "--detach", merge)
                result, record = self.record(LANE="base-merge", EXPECTED_TESTED_SHA=merge, FULL_WORKSPACE="true")
                valid = parents == (self.base, self.source)
                self.assertEqual(result.returncode == 0, valid, result.stderr)
                self.assertEqual(record["identity_valid"], valid)
                self.assertEqual(record["parents"], list(parents))
                self.assertEqual(record["tested_tree"], tree)
                self.assertEqual(record["test_command"], ["just", "test", "--locked"])

    def test_wrong_commit_and_dirty_tracked_content_cannot_publish_valid_identity(self):
        result, record = self.record(EXPECTED_TESTED_SHA=self.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(record["identity_valid"])
        (self.root / "input").write_text("uncommitted mutation\n")
        result, record = self.record()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(record["tracked_clean"])
        self.assertFalse(record["identity_valid"])


if __name__ == "__main__":
    unittest.main()
