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
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hepta-consolidated-source.yml"


def step(name: str) -> str:
    text = WORKFLOW.read_text(encoding="utf-8").split("  qualification:\n", 1)[1]
    match = re.search(r"^      - name: " + re.escape(name) + r"\n", text, re.M)
    if match is None:
        raise AssertionError(f"missing qualification step: {name}")
    following = re.search(r"^      - ", text[match.end() :], re.M)
    end = match.end() + following.start() if following else len(text)
    return text[match.start() : end]


def shell(name: str) -> str:
    block = step(name)
    marker = "        run: |\n"
    if marker not in block:
        raise AssertionError(f"expected block shell for {name}")
    lines = block.split(marker, 1)[1].splitlines()
    if not all(not line or line.startswith("          ") for line in lines):
        raise AssertionError("unexpected shell indentation")
    return "\n".join(line[10:] if line else "" for line in lines) + "\n"


def engineering_step(name: str) -> str:
    text = (
        WORKFLOW.read_text(encoding="utf-8")
        .split("  engineering-sandbox:\n", 1)[1]
        .split("  os-evidence:\n", 1)[0]
    )
    match = re.search(r"^      - name: " + re.escape(name) + r"\n", text, re.M)
    if match is None:
        raise AssertionError(f"missing engineering-sandbox step: {name}")
    following = re.search(r"^      - ", text[match.end() :], re.M)
    end = match.end() + following.start() if following else len(text)
    return text[match.start() : end]


def engineering_shell(name: str) -> str:
    block = engineering_step(name)
    marker = "        run: |\n"
    if marker not in block:
        raise AssertionError(f"expected engineering-sandbox shell for {name}")
    lines = block.split(marker, 1)[1].splitlines()
    if not all(not line or line.startswith("          ") for line in lines):
        raise AssertionError("unexpected engineering-sandbox shell indentation")
    return "\n".join(line[10:] if line else "" for line in lines) + "\n"


class NativeFeedbackPolicyTests(unittest.TestCase):
    def test_native_feedback_precedes_document_gate(self):
        text = WORKFLOW.read_text()
        self.assertLess(
            text.index("      - name: Compile and test actual imported packages\n"),
            text.index(
                "      - name: Retain original document and source-owner gates\n"
            ),
        )

    def test_manifest_and_format_checks_precede_native_setup(self):
        text = WORKFLOW.read_text()
        names = [
            "Verify executable candidate identity",
            "Check workspace structure before native setup",
            "Parse actual Cargo workspace before native setup",
            "Formatting without source mutation",
            "Prepare native owner-test prerequisites",
        ]
        positions = [text.index("      - name: " + name + "\n") for name in names]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("scripts/hepta_workspace.py", shell(names[1]))
        self.assertIn(
            "cargo metadata --locked --format-version 1 --no-deps", shell(names[2])
        )

    def test_failure_independence_requires_successful_identity_or_setup(self):
        for name in (
            "UI owner tests independently of document outcome",
            "Clean tracked source",
        ):
            with self.subTest(name=name):
                self.assertIn(
                    "if: ${{ !cancelled() && steps.candidate.outcome == 'success' }}",
                    step(name),
                )
        self.assertIn(
            "if: ${{ !cancelled() && steps.native_ready.outcome == 'success' }}",
            step("Strict Clippy independently of test outcome"),
        )
        self.assertIn("id: candidate", step("Verify executable candidate identity"))
        self.assertIn(
            "id: native_ready",
            step("Resolve verified sandboxed V8 artifacts for Cargo"),
        )
        # Setup and native execution keep Actions' default success() guard.
        self.assertNotRegex(
            step("Verify executable candidate identity"), r"\n        if:"
        )
        for name in (
            "Prepare native owner-test prerequisites",
            "Resolve verified sandboxed V8 artifacts for Cargo",
            "Compile and test actual imported packages",
        ):
            self.assertIn("if: steps.impact.outputs.has_packages == 'true'", step(name))
            self.assertNotIn("!cancelled()", step(name))

    def test_no_failure_suppression_or_privileged_event(self):
        text = WORKFLOW.read_text()
        self.assertNotIn("continue-on-error", text)
        self.assertNotRegex(text, r"\|\|\s*true\b")
        self.assertNotIn("pull_request_target:", text)
        self.assertNotIn("contents: write", text)
        self.assertNotIn("secrets:", text)
        self.assertIn("contents: read", text)
        self.assertNotIn(
            "cargo check", text
        )  # Do not compile everything twice just for ordering.

    def test_engineering_sandbox_binds_the_actual_matrix_candidate(self):
        synthetic = engineering_step("Construct deterministic sandbox merge candidate")
        binding = engineering_step("Bind exact engineering sandbox candidate identity")
        self.assertIn("id: sandbox-synthetic", synthetic)
        self.assertIn(
            "TESTED_SHA: ${{ steps.sandbox-synthetic.outputs.sha || env.SOURCE_SHA }}",
            binding,
        )
        self.assertIn("HEPTA_CI_LANE: ${{ matrix.lane }}", binding)
        script = engineering_shell("Bind exact engineering sandbox candidate identity")
        self.assertIn('test "$(git rev-parse HEAD)" = "$TESTED_SHA"', script)
        self.assertIn("printf 'TESTED_SHA=%s\\n'", script)
        self.assertIn("printf 'HEPTA_CI_LANE=%s\\n'", script)

    def test_records_and_raw_output_are_both_uploaded(self):
        text = WORKFLOW.read_text()
        paths = re.findall(r"path: .*?/hepta-command-records/([^\n]+)", text)
        self.assertEqual(len(paths), 4)
        for pattern in paths:
            self.assertTrue(fnmatch.fnmatchcase("owner-test.json", pattern))
            self.assertTrue(fnmatch.fnmatchcase("owner-test.json.1234.log", pattern))

    def test_build_and_policy_inputs_reach_the_aggregate_checks(self):
        from scripts.hepta_ci_scope import select

        # The consolidated workflow is now reusable. Automatic dispatch belongs
        # to the aggregate, whose dependency selector must retain build inputs.
        text = WORKFLOW.read_text().split("permissions:", 1)[0]
        self.assertIn("  workflow_call:", text)
        aggregate = (ROOT / ".github/workflows/blocking-ci.yml").read_text()
        events = aggregate.split("concurrency:", 1)[0]
        self.assertIn("  pull_request:", events)
        self.assertNotIn("paths:", events)
        self.assertIn("needs.scope.outputs.native == 'true'", aggregate)
        for path in (
            ".cargo/config.toml",
            "codex-rs/.cargo/config.toml",
            "rust-toolchain",
            "rust-toolchain.toml",
            "codex-rs/rust-toolchain",
            "codex-rs/rust-toolchain.toml",
        ):
            with self.subTest(path=path):
                self.assertTrue(select([path])["native"])
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
        shutil.copyfile(
            ROOT / "scripts/hepta_ci_dependencies.py",
            self.repo / "scripts/hepta_ci_dependencies.py",
        )
        (self.repo / "scripts/hepta-gap-closure.py").write_text(
            'import os\nprint("document diagnostic sentinel")\nraise SystemExit(int(os.environ.get("DOC_RC", "0")))\n'
        )
        (self.repo / "codex-rs/code.rs").write_text("fn main() {}\n")
        (self.repo / "codex-rs/Cargo.toml").write_text(
            '[workspace]\nmembers=["owner-a","owner-b","unrelated"]\n'
        )
        for package in ("owner-a", "owner-b", "unrelated"):
            directory = self.repo / "codex-rs" / package
            (directory / "src").mkdir(parents=True)
            (directory / "Cargo.toml").write_text(
                f'[package]\nname="{package}"\nversion="0.1.0"\n'
            )
            (directory / "src/lib.rs").write_text("pub fn value() -> u32 { 1 }\n")
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
            "FULL_QUALIFICATION": "false",
            "HEPTA_CI_LANE": "source-head",
            "MERGE_SHA": "",
        }
        self.git("init", "--quiet")
        self.git("config", "user.name", "Workflow Test")
        self.git("config", "user.email", "workflow-test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.base = self.commit()
        for package in ("owner-a", "owner-b"):
            (self.repo / "codex-rs" / package / "src/lib.rs").write_text(
                "pub fn value() -> u32 { 2 }\n"
            )
        self.head = self.commit()
        self.env.update(SOURCE_SHA=self.head, TESTED_SHA=self.head, BASE_SHA=self.base)

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
            if "working-directory: codex-rs\n" in step(name)
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
        result = self.invoke("Verify executable candidate identity")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [])

    def test_wrong_candidate_and_dirty_source_reject_before_dispatch(self):
        self.assertNotEqual(
            self.invoke(
                "Verify executable candidate identity", TESTED_SHA="f" * 40
            ).returncode,
            0,
        )
        (self.repo / "codex-rs/code.rs").write_text("edited after checkout\n")
        self.assertNotEqual(
            self.invoke("Verify executable candidate identity").returncode, 0
        )
        self.assertEqual(self.calls(), [])

    def test_merge_lane_cannot_fall_back_to_source_head(self):
        result = self.invoke(
            "Verify executable candidate identity",
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
                    engineering_shell(
                        "Bind exact engineering sandbox candidate identity"
                    ),
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
        result = self.invoke(
            "Parse actual Cargo workspace before native setup", FAIL_METADATA="47"
        )
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
        result = self.invoke("Formatting without source mutation", FAIL_FMT="41")
        self.assertEqual(result.returncode, 41, result.stderr)
        self.assertEqual(self.record("format.json")["status"], "failed")
        self.assertEqual(
            self.calls(),
            [["cargo", "fmt", "-p", "owner-a", "-p", "owner-b", "--", "--check"]],
        )

    def test_native_failure_and_strict_clippy_have_independent_records(self):
        failed = self.invoke(
            "Compile and test actual imported packages", FAIL_JUST="19"
        )
        self.assertEqual(failed.returncode, 19, failed.stderr)
        lint = self.invoke("Strict Clippy independently of test outcome")
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
        result = self.invoke(
            "Strict Clippy independently of test outcome", FAIL_CLIPPY="37"
        )
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(self.record("clippy.json")["status"], "failed")

    def test_document_failure_does_not_consume_ui_feedback(self):
        failed = self.invoke(
            "Retain original document and source-owner gates", DOC_RC="31"
        )
        self.assertEqual(failed.returncode, 31, failed.stderr)
        ui = self.invoke("UI owner tests independently of document outcome")
        self.assertEqual(ui.returncode, 0, ui.stderr)
        self.assertEqual(self.record("source-owner.json")["status"], "failed")
        self.assertEqual(self.record("ui-test.json")["status"], "passed")

    def test_actual_record_log_is_in_upload_set(self):
        result = self.invoke(
            "Compile and test actual imported packages", FAIL_JUST="19"
        )
        self.assertEqual(result.returncode, 19)
        record = self.record("owner-test.json")
        directory = Path(self.env["RUNNER_TEMP"]) / "hepta-command-records"
        log = directory / record["log_file"]
        self.assertIn("native stand-in diagnostic: just", log.read_text())
        self.assertEqual(
            hashlib.sha256(log.read_bytes()).hexdigest(), record["log_sha256"]
        )
        pattern = re.search(
            r"path: .*?/hepta-command-records/([^\n]+)",
            step("Retain real command records"),
        )[1]
        self.assertIn(log, list(directory.glob(pattern)))

    def test_consolidated_native_checks_share_the_real_dependency_plan(self):
        output = self.root / "github-output"
        result = self.invoke(
            "Compute affected owners from both exact Cargo graphs",
            GITHUB_OUTPUT=str(output),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_text(), "has_packages=true\n")
        self.assertEqual(
            self.record("cargo-impact.json")["packages"], ["owner-a", "owner-b"]
        )
        for name in (
            "Formatting without source mutation",
            "Compile and test actual imported packages",
            "Strict Clippy independently of test outcome",
        ):
            result = self.invoke(name)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.calls(),
            [
                ["cargo", "fmt", "-p", "owner-a", "-p", "owner-b", "--", "--check"],
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

    def test_explicit_full_qualification_executes_workspace(self):
        result = self.invoke(
            "Compile and test actual imported packages", FULL_QUALIFICATION="true"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [["just", "test", "--locked", "--workspace"]])

    def test_missing_base_executes_workspace(self):
        result = self.invoke(
            "Compile and test actual imported packages", BASE_SHA="f" * 40
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [["just", "test", "--locked", "--workspace"]])

    def test_empty_diff_never_invokes_native_commands(self):
        for name in (
            "Formatting without source mutation",
            "Compile and test actual imported packages",
            "Strict Clippy independently of test outcome",
        ):
            result = self.invoke(name, BASE_SHA=self.head)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [])

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
        self.assertEqual(
            self.invoke("Verify executable candidate identity").returncode, 0
        )
        result = self.invoke("Parse actual Cargo workspace before native setup")
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
        result = self.invoke("Parse actual Cargo workspace before native setup")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.record("workspace-metadata.json")["status"], "rejected")
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
