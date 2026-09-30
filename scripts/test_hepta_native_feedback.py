"""Exercise the native workflow's real shell and execution-record owner.

Cargo, nextest (just) and Node are stand-ins: these tests prove argument/exit
propagation, candidate identity and retained diagnostics, NOT a native build,
product lifecycle or independent qualification. Git repositories and synthetic
merge objects are real. No extra YAML dependency is needed on the CI runner.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts.hepta_workflow_commands import (
    load_workflow,
    run_scalar_commands,
    workflow_contains_key,
    workflow_events,
    workflow_expression_functions,
    workflow_expression_references,
    workflow_run,
    workflow_step_by_id,
    workflow_steps,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hepta-consolidated-source.yml"
WORKFLOW_DOCUMENT = load_workflow(WORKFLOW.read_text(encoding="utf-8"))


def step(step_id: str) -> dict:
    return workflow_step_by_id(WORKFLOW_DOCUMENT, "qualification", step_id)


def shell(name: str) -> str:
    return workflow_run(step(name))


def engineering_step(step_id: str) -> dict:
    return workflow_step_by_id(WORKFLOW_DOCUMENT, "engineering-sandbox", step_id)


def engineering_shell(name: str) -> str:
    return workflow_run(engineering_step(name))


def command_lines(value: dict) -> list[list[str]]:
    return run_scalar_commands(value.get("run", ""))


def command_records_upload(job_name: str) -> dict:
    matches = [
        value
        for value in workflow_steps(WORKFLOW_DOCUMENT, job_name)
        if str(value.get("uses", "")).startswith("actions/upload-artifact@")
        and "hepta-command-records" in str(value.get("with", {}).get("path", ""))
    ]
    if len(matches) != 1:
        raise ValueError(f"job {job_name} requires one command-record upload")
    return matches[0]


def contains_subsequence(command: list[str], expected: list[str]) -> bool:
    return any(
        command[index : index + len(expected)] == expected
        for index in range(len(command))
    )


class NativeFeedbackPolicyTests(unittest.TestCase):
    def qualification_step_index(self, name: str) -> int:
        return workflow_steps(WORKFLOW_DOCUMENT, "qualification").index(step(name))

    def test_native_feedback_precedes_document_gate(self):
        self.assertLess(
            self.qualification_step_index("owner-tests"),
            self.qualification_step_index("document-gates"),
        )

    def test_manifest_and_format_checks_precede_native_setup(self):
        names = [
            "candidate",
            "workspace-structure",
            "workspace-metadata",
            "formatting",
            "native-prerequisites",
        ]
        positions = [self.qualification_step_index(name) for name in names]
        self.assertEqual(positions, sorted(positions))
        self.assertIn(
            ["python3", "scripts/hepta_workspace.py"], command_lines(step(names[1]))
        )
        metadata = [
            "cargo",
            "metadata",
            "--locked",
            "--format-version",
            "1",
            "--no-deps",
        ]
        self.assertTrue(
            any(
                contains_subsequence(command, metadata)
                for command in command_lines(step(names[2]))
            )
        )
        self.assertEqual(step(names[2]).get("working-directory"), "codex-rs")
        self.assertEqual(step(names[3]).get("working-directory"), "codex-rs")

    def test_failure_independence_is_dataflow_bound(self):
        for name in (
            "document-gates",
            "ui-tests",
            "clean-source",
        ):
            with self.subTest(name=name):
                condition = step(name).get("if")
                self.assertIn("cancelled", workflow_expression_functions(condition))
                self.assertIn(
                    "steps.candidate.outcome", workflow_expression_references(condition)
                )
        condition = step("strict-clippy").get("if")
        self.assertIn("cancelled", workflow_expression_functions(condition))
        self.assertIn(
            "steps.native_ready.outcome", workflow_expression_references(condition)
        )
        self.assertEqual(step("candidate").get("id"), "candidate")
        self.assertEqual(step("native_ready").get("id"), "native_ready")
        for name in (
            "candidate",
            "native-prerequisites",
            "native_ready",
            "owner-tests",
        ):
            self.assertNotIn("if", step(name))

    def test_no_failure_suppression_or_privileged_event(self):
        self.assertFalse(workflow_contains_key(WORKFLOW_DOCUMENT, "continue-on-error"))
        self.assertNotIn("pull_request_target", workflow_events(WORKFLOW_DOCUMENT))
        self.assertEqual(WORKFLOW_DOCUMENT.get("permissions"), {"contents": "read"})
        self.assertFalse(workflow_contains_key(WORKFLOW_DOCUMENT, "secrets"))
        commands = [
            command
            for job in WORKFLOW_DOCUMENT["jobs"].values()
            for workflow_step_value in job.get("steps", [])
            for command in command_lines(workflow_step_value)
        ]
        self.assertFalse(any(command[-2:] == ["||", "true"] for command in commands))
        self.assertFalse(any(command[:2] == ["cargo", "check"] for command in commands))

    def test_engineering_sandbox_binds_actual_matrix_candidate(self):
        synthetic = engineering_step("sandbox-synthetic")
        binding = engineering_step("sandbox-candidate")
        self.assertEqual(synthetic.get("id"), "sandbox-synthetic")
        references = workflow_expression_references(binding.get("env", {}))
        self.assertIn("steps.sandbox-synthetic.outputs.sha", references)
        self.assertIn("matrix.lane", references)
        self.assertEqual(
            binding.get("env", {}).get("HEPTA_CI_LANE"), "${{ matrix.lane }}"
        )

    def test_records_and_raw_output_are_both_uploaded(self):
        paths = []
        for job in WORKFLOW_DOCUMENT["jobs"].values():
            for value in job.get("steps", []):
                if str(value.get("uses", "")).startswith("actions/upload-artifact@"):
                    candidate = value.get("with", {}).get("path")
                    if (
                        isinstance(candidate, str)
                        and "hepta-command-records" in candidate
                    ):
                        paths.append(candidate.rsplit("/", 1)[-1])
        self.assertEqual(len(paths), 4)
        for pattern in paths:
            self.assertTrue(fnmatch.fnmatchcase("owner-test.json", pattern))
            self.assertTrue(fnmatch.fnmatchcase("owner-test.json.1234.log", pattern))

    def test_build_inputs_reach_the_unfiltered_aggregate_scope(self):
        from scripts.hepta_ci_scope import select

        self.assertIn("workflow_call", workflow_events(WORKFLOW_DOCUMENT))
        self.assertNotIn("pull_request", workflow_events(WORKFLOW_DOCUMENT))
        aggregate = load_workflow(
            (ROOT / ".github/workflows/blocking-ci.yml").read_text()
        )
        self.assertIn("pull_request", workflow_events(aggregate))
        self.assertIsInstance(aggregate.get("on", {}).get("pull_request"), dict)
        for path in (
            ".cargo/config.toml",
            "codex-rs/.cargo/config.toml",
            "rust-toolchain",
            "rust-toolchain.toml",
            "codex-rs/rust-toolchain",
            "codex-rs/rust-toolchain.toml",
        ):
            with self.subTest(path=path):
                selected = select([path])
                self.assertTrue(selected["full_repo"])
                self.assertTrue(selected["native"])
        for path in (
            "scripts/hepta_workspace.py",
            "scripts/test_hepta_native_feedback.py",
        ):
            with self.subTest(path=path):
                self.assertTrue(select([path])["derived"])


class NativeFeedbackExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "source"
        self.repo.mkdir()
        (self.repo / "codex-rs").mkdir()
        (self.repo / "scripts").mkdir()
        shutil.copyfile(
            ROOT / "scripts/hepta_ci_exec.py", self.repo / "scripts/hepta_ci_exec.py"
        )
        (self.repo / "scripts/hepta-gap-closure.py").write_text(
            'import os\nprint("document diagnostic sentinel")\nraise SystemExit(int(os.environ.get("DOC_RC", "0")))\n'
        )
        (self.repo / "codex-rs/code.rs").write_text("fn main() {}\n")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        tool = """import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
phase = sys.argv[1] if name == "cargo" else name
with open(os.environ["TOOL_CALLS"], "a") as output:
    output.write(json.dumps([name, *sys.argv[1:]]) + "\\n")
print("native stand-in diagnostic: " + phase, flush=True)
raise SystemExit(int(os.environ.get("FAIL_" + phase.upper(), "0")))
"""
        for name in ("cargo", "just", "node"):
            path = self.bin / name
            path.write_text("#!" + sys.executable + "\n" + tool)
            path.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "RUNNER_TEMP": str(self.root / "records"),
            "TOOL_CALLS": str(self.root / "calls.jsonl"),
            "PACKAGES": "owner-a owner-b",
            "HEPTA_CI_LANE": "source-head",
            "MERGE_SHA": "",
        }
        self.git("init", "--quiet")
        self.git("config", "user.name", "Workflow Test")
        self.git("config", "user.email", "workflow-test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.head = self.commit()
        self.env.update(SOURCE_SHA=self.head, TESTED_SHA=self.head, BASE_SHA=self.head)

    def git(self, *args):
        return subprocess.check_output(
            ["git", *args],
            cwd=self.repo,
            env=self.env,
            text=True,
            stderr=subprocess.PIPE,
        ).strip()

    def commit(self):
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "workflow fixture")
        return self.git("rev-parse", "HEAD")

    def invoke(self, name, **extra):
        cwd = (
            self.repo / "codex-rs"
            if step(name).get("working-directory") == "codex-rs"
            else self.repo
        )
        return subprocess.run(
            ["bash", "-c", shell(name)],
            cwd=cwd,
            env={**self.env, **extra},
            text=True,
            capture_output=True,
            timeout=20,
        )

    def record(self, name):
        return json.loads(
            (Path(self.env["RUNNER_TEMP"]) / "hepta-command-records" / name).read_text()
        )

    def calls(self):
        path = Path(self.env["TOOL_CALLS"])
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def test_source_candidate_identity_is_real_git(self):
        result = self.invoke("candidate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [])

    def test_wrong_candidate_and_dirty_source_reject_before_dispatch(self):
        self.assertNotEqual(
            self.invoke("candidate", TESTED_SHA="f" * 40).returncode,
            0,
        )
        (self.repo / "codex-rs/code.rs").write_text("edited after checkout\n")
        self.assertNotEqual(self.invoke("candidate").returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_merge_lane_cannot_fall_back_to_source_head(self):
        result = self.invoke(
            "candidate",
            HEPTA_CI_LANE="base-merge",
            MERGE_SHA="",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_engineering_sandbox_identity_shell_binds_source_and_merge_lanes(self):
        output = self.root / "engineering-github-env"

        def invoke(**extra):
            output.write_text("")
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    engineering_shell("sandbox-candidate"),
                ],
                cwd=self.repo,
                env={**self.env, "GITHUB_ENV": str(output), **extra},
                text=True,
                capture_output=True,
                timeout=20,
            )
            return result, output.read_text()

        source, source_env = invoke(MERGE_SHA="")
        self.assertEqual(source.returncode, 0, source.stderr)
        self.assertEqual(
            source_env,
            f"TESTED_SHA={self.head}\nHEPTA_CI_LANE=source-head\n",
        )

        self.merge_fixture()
        merge, merge_env = invoke()
        self.assertEqual(merge.returncode, 0, merge.stderr)
        self.assertEqual(
            merge_env,
            f"TESTED_SHA={self.env['TESTED_SHA']}\nHEPTA_CI_LANE=base-merge\n",
        )
        fallback, fallback_env = invoke(
            TESTED_SHA=self.env["SOURCE_SHA"],
            MERGE_SHA="",
        )
        self.assertNotEqual(fallback.returncode, 0)
        self.assertEqual(fallback_env, "")

    def test_metadata_failure_is_retained_and_not_called_a_test_pass(self):
        result = self.invoke("workspace-metadata", FAIL_METADATA="47")
        self.assertEqual(result.returncode, 47, result.stderr)
        record = self.record("workspace-metadata.json")
        self.assertEqual(
            (record["status"], record["command_exit_code"]), ("failed", 47)
        )
        self.assertEqual(record["observed_passed_tests"], 0)
        self.assertEqual(
            self.calls(),
            [["cargo", "metadata", "--locked", "--format-version", "1", "--no-deps"]],
        )

    def test_format_failure_is_not_suppressed(self):
        result = self.invoke("formatting", FAIL_FMT="41")
        self.assertEqual(result.returncode, 41, result.stderr)
        self.assertEqual(self.record("format.json")["status"], "failed")
        self.assertEqual(
            self.calls(),
            [
                [
                    "cargo",
                    "fmt",
                    "--package",
                    "owner-a",
                    "--package",
                    "owner-b",
                    "--",
                    "--check",
                ]
            ],
        )

    def test_native_failure_and_strict_clippy_have_independent_records(self):
        failed = self.invoke("owner-tests", FAIL_JUST="19")
        self.assertEqual(failed.returncode, 19, failed.stderr)
        lint = self.invoke("strict-clippy")
        self.assertEqual(lint.returncode, 0, lint.stderr)
        self.assertEqual(self.record("owner-test.json")["status"], "failed")
        self.assertEqual(self.record("clippy.json")["status"], "passed")
        self.assertEqual(
            self.calls(),
            [
                ["just", "test", "--locked", "-p", "owner-a", "-p", "owner-b"],
                [
                    "cargo",
                    "clippy",
                    "--locked",
                    "-p",
                    "owner-a",
                    "-p",
                    "owner-b",
                    "--all-targets",
                    "--",
                    "-D",
                    "warnings",
                ],
            ],
        )

    def test_clippy_failure_remains_a_failed_gate(self):
        result = self.invoke("strict-clippy", FAIL_CLIPPY="37")
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(self.record("clippy.json")["status"], "failed")

    def test_document_failure_does_not_consume_ui_feedback(self):
        failed = self.invoke("document-gates", DOC_RC="31")
        self.assertEqual(failed.returncode, 31, failed.stderr)
        ui = self.invoke("ui-tests")
        self.assertEqual(ui.returncode, 0, ui.stderr)
        self.assertEqual(self.record("source-owner.json")["status"], "failed")
        self.assertEqual(self.record("ui-test.json")["status"], "passed")

    def test_actual_record_log_is_in_upload_set(self):
        result = self.invoke("owner-tests", FAIL_JUST="19")
        self.assertEqual(result.returncode, 19)
        record = self.record("owner-test.json")
        directory = Path(self.env["RUNNER_TEMP"]) / "hepta-command-records"
        log = directory / record["log_file"]
        self.assertIn("native stand-in diagnostic: just", log.read_text())
        self.assertEqual(
            hashlib.sha256(log.read_bytes()).hexdigest(), record["log_sha256"]
        )
        upload = command_records_upload("qualification")
        pattern = upload["with"]["path"].rsplit("/", 1)[-1]
        self.assertIn(log, list(directory.glob(pattern)))

    def merge_fixture(self, *, wrong_tree=False):
        (self.repo / "source-only").write_text("source\n")
        source = self.commit()
        self.git("checkout", "--quiet", "--detach", self.head)
        (self.repo / "base-only").write_text("base\n")
        base = self.commit()
        tree = self.git("merge-tree", "--write-tree", base, source)
        if wrong_tree:
            tree = self.git("rev-parse", source + "^{tree}")
        merge = self.git(
            "commit-tree", tree, "-p", base, "-p", source, "-m", "synthetic fixture"
        )
        self.git("checkout", "--quiet", "--detach", merge)
        self.env.update(
            SOURCE_SHA=source,
            BASE_SHA=base,
            TESTED_SHA=merge,
            MERGE_SHA=merge,
            HEPTA_CI_LANE="base-merge",
        )

    def test_prospective_merge_record_binds_real_tree_and_both_parents(self):
        self.merge_fixture()
        self.assertEqual(self.invoke("candidate").returncode, 0)
        result = self.invoke("workspace-metadata")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = self.record("workspace-metadata.json")
        self.assertEqual(
            record["before"]["parents"], [self.env["BASE_SHA"], self.env["SOURCE_SHA"]]
        )
        self.assertEqual(
            record["recomputed_merge_tree"], self.git("rev-parse", "HEAD^{tree}")
        )

    def test_noncanonical_merge_tree_does_not_run_native_command(self):
        self.merge_fixture(wrong_tree=True)
        result = self.invoke("workspace-metadata")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.record("workspace-metadata.json")["status"], "rejected")
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
