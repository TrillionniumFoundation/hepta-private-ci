"""Execute the workflow's Git construction shell against isolated repositories."""

import contextlib
import io
import os
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

import hepta_ui_native_aggregate as aggregate

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/ui-native-qualification.yml"
)


def shell_step(name: str) -> str:
    section = WORKFLOW.read_text(encoding="utf-8").split(f"      - name: {name}\n", 1)[
        1
    ]
    body = section.split("        run: |\n", 1)[1].split("      - ", 1)[0]
    return textwrap.dedent(body)


def bash_executable() -> str:
    # Actions selects Git Bash explicitly on Windows; a bare name can select WSL.
    if sys.platform == "win32":
        git = shutil.which("git")
        if git is not None:
            for parent in Path(git).resolve().parents:
                candidate = parent / "bin/bash.exe"
                if candidate.is_file():
                    return str(candidate)
        raise RuntimeError("workflow tests require the installed Git for Windows Bash")
    if sys.platform == "darwin":
        bash = Path("/bin/bash")
        if not bash.is_file():
            raise RuntimeError("workflow tests require native macOS /bin/bash")
        return str(bash)
    bash = shutil.which("bash")
    if bash is None:
        raise RuntimeError("workflow tests require Bash")
    return bash


class ShellSelectionTests(unittest.TestCase):
    def test_windows_uses_git_bash_even_with_another_bash_on_path(self):
        with tempfile.TemporaryDirectory(prefix="ui native shell ") as temporary:
            root = Path(temporary).resolve()
            git = root / "Git/cmd/git.exe"
            bash = root / "Git/bin/bash.exe"
            other_bash = root / "WSL/bash.exe"
            for path in (git, bash, other_bash):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            with (
                patch.object(sys, "platform", "win32"),
                patch.object(
                    shutil,
                    "which",
                    side_effect=lambda name: str(git if name == "git" else other_bash),
                ) as which,
            ):
                self.assertEqual(Path(bash_executable()), bash)
                which.assert_called_once_with("git")

    def test_windows_without_git_bash_fails_instead_of_using_another_shell(self):
        with tempfile.TemporaryDirectory(prefix="ui native shell ") as temporary:
            git = Path(temporary).resolve() / "Git/cmd/git.exe"
            git.parent.mkdir(parents=True)
            git.write_bytes(b"fixture")
            with (
                patch.object(sys, "platform", "win32"),
                patch.object(shutil, "which", return_value=str(git)),
                self.assertRaisesRegex(RuntimeError, "Git for Windows Bash"),
            ):
                bash_executable()


class PlatformConstructionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ui native workflow ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "repo"
        self.root.mkdir()
        self.runner_temp = Path(self.temp.name).resolve() / "runner"
        self.output = self.runner_temp / "ui-native-platform"
        self.git("init", "--quiet")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "user.name", "fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.root / "source.rs").write_text("source\n", encoding="utf-8", newline="\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "base")
        self.base = self.git("rev-parse", "HEAD").strip()
        (self.root / "source.rs").write_text(
            "candidate\n", encoding="utf-8", newline="\n"
        )
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "candidate")
        self.candidate = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True)

    def construct(self, kind):
        return subprocess.run(
            [
                bash_executable(),
                "-c",
                shell_step("Construct exact head or fixed ordered-parent merge"),
            ],
            cwd=self.root,
            env={
                **os.environ,
                "CANDIDATE": self.candidate,
                "BASE": self.base,
                "KIND": kind,
                "RUNNER_TEMP": self.runner_temp.as_posix(),
                "GITHUB_ENV": (
                    Path(self.temp.name).resolve() / "github-env"
                ).as_posix(),
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_exact_head_records_evidence_without_dirtying_checkout(self):
        result = self.construct("head")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.candidate)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertIn(
            f"commit={self.candidate}",
            (self.output / "native-evidence/source.txt").read_text(),
        )
        exported = (Path(self.temp.name) / "github-env").read_text()
        self.assertIn(f"NATIVE_OUTPUT_ROOT={self.output.as_posix()}\n", exported)

    def test_storage_preparation_exports_target_for_later_steps(self):
        implementation = "a" * 40
        state = self.root / "apps/hepta-native/CANDIDATE.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"implementationSourceSha": implementation}))
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "storage subject")
        candidate = self.git("rev-parse", "HEAD").strip()
        script = shell_step("Prepare exact implementation evidence paths")
        script = script.replace("${{ needs.subject.outputs.candidate }}", candidate)
        script = script.replace(
            "${{ needs.subject.outputs.implementation }}", implementation
        )
        exported = Path(self.temp.name) / "storage-github-env"
        result = subprocess.run(
            [bash_executable(), "-c", script],
            cwd=self.root,
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "RUNNER_TEMP": self.runner_temp.as_posix(),
                "GITHUB_ENV": exported.as_posix(),
            },
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        later_env = dict(
            line.split("=", 1) for line in exported.read_text().splitlines()
        )
        later = subprocess.run(
            [
                bash_executable(),
                "-c",
                'printf "%s\\n%s\\n" "$CARGO_TARGET_DIR" "$IMPLEMENTATION_SHA"',
            ],
            cwd=self.root,
            text=True,
            capture_output=True,
            env={**os.environ, **later_env},
        )
        self.assertEqual(later.returncode, 0, later.stdout + later.stderr)
        self.assertEqual(
            later.stdout.splitlines(),
            [
                (self.runner_temp / "ui-native-storage-target").as_posix(),
                implementation,
            ],
        )
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_merge_preserves_ordered_parents_and_clean_checkout(self):
        result = self.construct("merge")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.git("show", "-s", "--format=%P", "HEAD").strip(),
            f"{self.base} {self.candidate}",
        )
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertTrue((self.output / "native-evidence/source.txt").is_file())

    def test_merge_constructor_sends_binary_lf_and_matches_aggregate(self):
        script = shell_step("Construct exact head or fixed ordered-parent merge")
        constructor = script.split("<<'PYTHON'\n", 1)[1].split("\nPYTHON", 1)[0]
        tree = self.git("merge-tree", "--write-tree", self.base, self.candidate).strip()
        check_output = subprocess.check_output

        def binary_commit_tree(command, **kwargs):
            self.assertEqual(command[:2], ["git", "commit-tree"])
            self.assertIsInstance(kwargs["input"], bytes)
            self.assertFalse(kwargs.get("text", False))
            return check_output(command, cwd=self.root, **kwargs)

        output = io.StringIO()
        with (
            patch.dict(
                os.environ,
                {"TREE": tree, "BASE": self.base, "CANDIDATE": self.candidate},
            ),
            patch.object(subprocess, "check_output", side_effect=binary_commit_tree),
            contextlib.redirect_stdout(output),
        ):
            exec(compile(constructor, str(WORKFLOW), "exec"), {})
        merge = output.getvalue().strip()
        payload = check_output(["git", "cat-file", "commit", merge], cwd=self.root)
        self.assertEqual(
            payload.split(b"\n\n", 1)[1],
            b"deterministic ui.native qualification merge\n",
        )
        expected = aggregate.deterministic_subjects(
            self.root, self.candidate, self.base
        )
        self.assertEqual(merge, expected["merge"]["sourceSha"])
        result = self.construct("merge")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), merge)

    def test_head_and_merge_parse_quoted_python_with_native_platform_bash(self):
        script = shell_step("Construct exact head or fixed ordered-parent merge")
        script = script.replace(
            "import os\n",
            "import os\n"
            "# A comment's unmatched apostrophe must remain literal heredoc data.\n"
            "_quote_fixture = {\"double's\": 'single\\\"quoted'}\n",
            1,
        )
        expected = aggregate.deterministic_subjects(
            self.root, self.candidate, self.base
        )
        for kind in ("head", "merge"):
            with (
                self.subTest(kind=kind),
                patch(__name__ + ".shell_step", return_value=script),
            ):
                result = self.construct(kind)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                self.git("rev-parse", "HEAD").strip(), expected[kind]["sourceSha"]
            )

    def test_dirty_source_is_still_rejected(self):
        (self.root / "source.rs").write_text(
            "dirty source\n", encoding="utf-8", newline="\n"
        )
        result = self.construct("head")
        self.assertNotEqual(result.returncode, 0)


class StorageReleaseProfileTests(unittest.TestCase):
    def test_actual_storage_shell_commands_build_and_run_release_harness(self):
        with tempfile.TemporaryDirectory(prefix="ui native storage ") as temporary:
            root = Path(temporary).resolve()
            binary = root / "bin"
            binary.mkdir()
            commands = root / "commands.jsonl"
            cargo = binary / "cargo"
            cargo.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "with open(os.environ['CAPTURED_COMMANDS'], 'a') as output:\n"
                "    output.write(json.dumps(sys.argv[1:]) + '\\n')\n",
                encoding="utf-8",
                newline="\n",
            )
            strace = binary / "strace"
            strace.write_text(
                '#!/bin/sh\nwhile [ "$1" != "cargo" ]; do shift; done\nexec "$@"\n',
                encoding="utf-8",
                newline="\n",
            )
            cargo.chmod(0o755)
            strace.chmod(0o755)
            workflow = WORKFLOW.read_text(encoding="utf-8")
            for identifier in ("compile", "active", "retired"):
                section = workflow.split(f"      - id: {identifier}\n", 1)[1].split(
                    "      - ", 1
                )[0]
                run = section.split("        run: ", 1)[1]
                script = (
                    textwrap.dedent(run[2:]) if run.startswith("|\n") else run.strip()
                )
                script = (
                    'export PATH="$PWD/bin:$PATH"\n'
                    'test "$(command -v cargo)" = "$PWD/bin/cargo"\n'
                    'test "$(command -v strace)" = "$PWD/bin/strace"\n' + script
                )
                result = subprocess.run(
                    [bash_executable(), "-c", script],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    env={
                        **os.environ,
                        "PATH": f"{binary}{os.pathsep}{os.environ['PATH']}",
                        "CAPTURED_COMMANDS": str(commands),
                        "RUNNER_TEMP": root.as_posix(),
                        "IMPLEMENTATION_SHA": "a" * 40,
                    },
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            captured = [json.loads(line) for line in commands.read_text().splitlines()]
            self.assertEqual(len(captured), 3)
            for command in captured:
                cargo_arguments = (
                    command[: command.index("--")] if "--" in command else command
                )
                for argument in ("test", "--release", "--locked", "--lib"):
                    self.assertIn(argument, cargo_arguments)
            self.assertIn("--no-run", captured[0])
            self.assertIn(
                "storage_qualification_tests::storage_active_scale_qualification",
                captured[1],
            )
            self.assertIn(
                "storage_qualification_tests::storage_retirement_scale_qualification",
                captured[2],
            )


class RepositoryAggregateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ui native aggregate ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.storage_root = self.root / "storage-bundle"
        self.storage_root.mkdir()
        self.env = {
            **os.environ,
            "CANDIDATE": "a" * 40,
            "BASE": "b" * 40,
            "IMPLEMENTATION": "a" * 40,
            "WORKFLOW_SHA": "d" * 40,
            "GITHUB_RUN_ID": "101",
            "GITHUB_RUN_ATTEMPT": "1",
            "PYTHONPATH": str(Path(__file__).resolve().parent),
        }
        platform = {
            "qualificationPassed": True,
            "candidateSha": self.env["CANDIDATE"],
            "baseSha": self.env["BASE"],
            "implementationSourceSha": self.env["IMPLEMENTATION"],
            "workflowSha": self.env["WORKFLOW_SHA"],
            "runId": "101",
            "runAttempt": "1",
        }
        self.write("native-aggregate/platform-qualification.json", platform)
        outcomes = {
            "schema": "hepta.ui-native-storage-job-outcomes.v1",
            "sourceSha": self.env["IMPLEMENTATION"],
            "candidateSha": self.env["CANDIDATE"],
            "workflowSha": self.env["WORKFLOW_SHA"],
            "runId": "101",
            "runAttempt": "1",
            "compile": "success",
            "active": "success",
            "retired": "success",
            "validate": "success",
        }
        self.write("storage-bundle/job-outcomes.json", outcomes)
        spec = importlib.util.spec_from_file_location(
            "storage_aggregate_fixture",
            Path(__file__).with_name("test_hepta_ui_native_storage.py"),
        )
        fixtures = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixtures)
        fixture = fixtures.StorageQualificationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.validate()
        self.write("apps/hepta-native/STORAGE_BUDGETS.json", fixture.budgets)
        self.write("storage-bundle/active.json", fixture.active)
        self.write("storage-bundle/retired.json", fixture.retired)
        shutil.copyfile(fixture.trace, self.storage_root / "active.strace.1")
        qualification = fixtures.storage.validate_storage(
            self.root / "apps/hepta-native/STORAGE_BUDGETS.json",
            self.storage_root / "active.json",
            self.storage_root / "retired.json",
            self.storage_root / "active.strace",
            self.env["IMPLEMENTATION"],
        )
        self.write("storage-bundle/qualification.json", qualification)

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def digest(self, relative):
        return hashlib.sha256((self.root / relative).read_bytes()).hexdigest()

    def mutate(self, relative, key, value):
        path = self.root / relative
        data = json.loads(path.read_text())
        data[key] = value
        self.write(relative, data)

    def aggregate(self):
        return subprocess.run(
            [
                bash_executable(),
                "-c",
                shell_step("Bind platform aggregate and storage artifact"),
            ],
            cwd=self.root,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_same_run_retained_storage_inputs_are_accepted(self):
        result = self.aggregate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        final = json.loads(
            (self.root / "native-aggregate/qualification-result.json").read_text()
        )
        self.assertEqual(
            final["storageJobOutcomesSha256"],
            self.digest("storage-bundle/job-outcomes.json"),
        )

    def test_foreign_attempt_storage_is_rejected(self):
        self.mutate("storage-bundle/job-outcomes.json", "runAttempt", "2")
        self.assertNotEqual(self.aggregate().returncode, 0)

    def test_failed_storage_stage_is_rejected(self):
        self.mutate("storage-bundle/job-outcomes.json", "validate", "failure")
        self.assertNotEqual(self.aggregate().returncode, 0)

    def test_modified_raw_storage_inputs_are_rejected(self):
        self.mutate("storage-bundle/active.json", "fixture", False)
        self.assertNotEqual(self.aggregate().returncode, 0)

    def test_modified_trace_is_rejected(self):
        (self.storage_root / "active.strace.1").write_text("modified", encoding="utf-8")
        self.assertNotEqual(self.aggregate().returncode, 0)

    def test_foreign_platform_implementation_is_rejected(self):
        self.mutate(
            "native-aggregate/platform-qualification.json",
            "implementationSourceSha",
            "e" * 40,
        )
        self.assertNotEqual(self.aggregate().returncode, 0)

    def test_forged_pass_and_rehashed_over_budget_samples_are_rejected(self):
        path = self.storage_root / "active.json"
        active = json.loads(path.read_text())
        active["freshProcessOpenSamplesMilliseconds"] = [3000] * 20
        active["freshProcessOpenP95Milliseconds"] = 3000
        for observation in active["openProcessSamples"]:
            observation["elapsedMilliseconds"] = 3000
        self.write("storage-bundle/active.json", active)
        qualification = json.loads(
            (self.storage_root / "qualification.json").read_text()
        )
        qualification["activeEvidence"]["measurements"] = active
        qualification["activeEvidence"]["sha256"] = self.digest(
            "storage-bundle/active.json"
        )
        self.write("storage-bundle/qualification.json", qualification)
        result = self.aggregate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("open p95 exceeded", result.stderr)


if __name__ == "__main__":
    unittest.main()
