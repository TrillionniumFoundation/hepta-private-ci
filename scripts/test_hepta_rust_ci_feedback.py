#!/usr/bin/env python3
"""Execute the actual fast-CI shell with real Git histories and explicit job outcomes.

No Cargo build, GitHub API, credentials, or external-effect qualification is
performed. These tests protect selection/exit semantics, not product execution.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/rust-ci.yml"
FLAGS = ("ARGUMENT_COMMENT_LINT", "CODEX", "WORKFLOWS", "ARGUMENT_COMMENT_LINT_PACKAGE")
RESULTS = (
    "MANIFEST_RESULT",
    "GENERAL_RESULT",
    "BENCHMARK_RESULT",
    "SHEAR_RESULT",
    "ARGPKG_RESULT",
    "ARGLINT_RESULT",
)


def job_block(name: str) -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        r"(?ms)^  " + re.escape(name) + r":\n(.*?)(?=^  [\w-]+:|\Z)", text
    )
    if match is None:
        raise AssertionError(f"missing workflow job: {name}")
    return match.group(1)


def shell_block(job: str, step: str) -> str:
    text = job_block(job)
    text = text.split("      - name: " + step + "\n", 1)[1]
    text = text.split("        run: |\n", 1)[1]
    lines = []
    for line in text.splitlines():
        if line and not line.startswith("          "):
            break
        lines.append(line[10:] if line else "")
    return "\n".join(lines) + "\n"


class FastFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.root),
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "RUNNER_TEMP": str(self.root),
            "GITHUB_OUTPUT": str(self.root / "output"),
        }
        self.git("init", "--quiet")
        (self.repo / "README.md").write_text("initial\n", encoding="utf-8")
        self.base = self.commit()

    def git(self, *args: str) -> str:
        return subprocess.run(
            [
                "git",
                "-c",
                "user.name=CI fixture",
                "-c",
                "user.email=ci@example.invalid",
                *args,
            ],
            cwd=self.repo,
            env=self.env,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    def commit(self) -> str:
        self.git("add", "--all")
        self.git("commit", "--quiet", "--no-gpg-sign", "-m", "fixture")
        return self.git("rev-parse", "HEAD")

    def changed(self, relative: str) -> str:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("changed\n", encoding="utf-8")
        return self.commit()

    def detect(
        self, head: str, *, base: str | None = None, event: str = "pull_request"
    ):
        output = Path(self.env["GITHUB_OUTPUT"])
        output.unlink(missing_ok=True)
        result = subprocess.run(
            [
                "bash",
                "-c",
                shell_block("changed", "Detect changed paths (no external action)"),
            ],
            cwd=self.repo,
            env={
                **self.env,
                "EVENT_NAME": event,
                "BASE_SHA": base or self.base,
                "HEAD_SHA": head,
            },
            text=True,
            capture_output=True,
        )
        values = (
            dict(line.split("=", 1) for line in output.read_text().splitlines())
            if output.exists()
            else {}
        )
        return result, values

    def summarize(self, **overrides: str):
        env = {
            **self.env,
            "CHANGED_RESULT": "success",
            **{key: "success" for key in RESULTS},
            **{"NEEDS_CHANGED_OUTPUTS_" + key: "false" for key in FLAGS},
            **overrides,
        }
        return subprocess.run(
            ["bash", "-c", shell_block("results", "Summarize")],
            cwd=self.repo,
            env=env,
            text=True,
            capture_output=True,
        )

    def test_valid_empty_diff_is_not_an_error(self):
        result, flags = self.detect(self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(flags.values()), {"false"})
        self.assertEqual(len(flags), 4)

    def test_invalid_base_fails_without_skip_outputs(self):
        result, flags = self.detect(self.base, base="0" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(flags, {})

    def test_invalid_head_fails_without_skip_outputs(self):
        result, flags = self.detect("0" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(flags, {})

    def test_paths_with_newlines_are_literal_and_select_rust(self):
        result, flags = self.detect(self.changed("codex-rs/member/src/new\nname.rs"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(flags["codex"], "true")
        self.assertEqual(flags["argument_comment_lint"], "true")

    def test_deleted_source_selects_rust(self):
        present = self.changed("codex-rs/member/src/lib.rs")
        (self.repo / "codex-rs/member/src/lib.rs").unlink()
        result, flags = self.detect(self.commit(), base=present)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(flags["codex"], "true")

    def test_prose_only_change_keeps_scoped_skip(self):
        result, flags = self.detect(self.changed("README.md"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(flags.values()), {"false"})

    def test_shared_build_inputs_select_manifest_checks(self):
        for path in (
            "justfile",
            ".cargo/config.toml",
            "rust-toolchain.toml",
            "scripts/hepta_workspace.py",
            "scripts/test_hepta_workspace.py",
            "scripts/test_hepta_rust_ci_feedback.py",
        ):
            with self.subTest(path=path):
                result, flags = self.detect(self.changed(path))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(flags["codex"], "true")

    def test_manual_run_still_selects_full_bundle(self):
        result, flags = self.detect(self.base, event="workflow_dispatch")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(flags.values()), {"true"})

    def test_detector_cleans_temporary_path_file(self):
        self.detect(self.base)
        self.detect(self.base, base="0" * 40)
        self.assertEqual(list(self.root.glob("rust-ci-paths.*")), [])

    def test_failed_cancelled_skipped_detection_cannot_pass(self):
        for result in ("failure", "cancelled", "skipped", ""):
            with self.subTest(result=result):
                self.assertNotEqual(self.summarize(CHANGED_RESULT=result).returncode, 0)

    def test_absent_or_invalid_flags_cannot_pass(self):
        for flag in FLAGS:
            for value in ("", "yes", "TRUE", "unknown"):
                with self.subTest(flag=flag, value=value):
                    self.assertNotEqual(
                        self.summarize(
                            **{
                                "NEEDS_CHANGED_OUTPUTS_" + flag: value,
                            }
                        ).returncode,
                        0,
                    )

    def test_confirmed_prose_only_change_can_pass(self):
        self.assertEqual(self.summarize().returncode, 0)

    def test_selected_rust_requires_all_four_results(self):
        for key in (
            "MANIFEST_RESULT",
            "GENERAL_RESULT",
            "BENCHMARK_RESULT",
            "SHEAR_RESULT",
        ):
            for result in ("failure", "cancelled", "skipped", ""):
                with self.subTest(key=key, result=result):
                    self.assertNotEqual(
                        self.summarize(
                            **{
                                "NEEDS_CHANGED_OUTPUTS_CODEX": "true",
                                key: result,
                            }
                        ).returncode,
                        0,
                    )
        self.assertEqual(
            self.summarize(NEEDS_CHANGED_OUTPUTS_CODEX="true").returncode, 0
        )

    def test_isolated_lint_package_flag_is_not_no_changes(self):
        self.assertNotEqual(
            self.summarize(
                NEEDS_CHANGED_OUTPUTS_ARGUMENT_COMMENT_LINT_PACKAGE="true",
                ARGPKG_RESULT="skipped",
            ).returncode,
            0,
        )

    def test_selected_lint_requires_success(self):
        self.assertNotEqual(
            self.summarize(
                NEEDS_CHANGED_OUTPUTS_ARGUMENT_COMMENT_LINT="true",
                ARGLINT_RESULT="failure",
            ).returncode,
            0,
        )

    def test_selected_workflows_require_both_lint_and_rust(self):
        self.assertNotEqual(
            self.summarize(
                NEEDS_CHANGED_OUTPUTS_WORKFLOWS="true",
                ARGLINT_RESULT="skipped",
            ).returncode,
            0,
        )
        self.assertNotEqual(
            self.summarize(
                NEEDS_CHANGED_OUTPUTS_WORKFLOWS="true",
                BENCHMARK_RESULT="failure",
            ).returncode,
            0,
        )

    def test_benchmark_is_preserved_but_does_not_delay_format_result(self):
        self.assertNotIn("bench-smoke", job_block("general"))
        self.assertIn("run: just bench-smoke", job_block("benchmark_smoke"))
        self.assertIn(
            "needs: [changed, workspace_manifest]", job_block("benchmark_smoke")
        )
        self.assertIn("needs: changed", job_block("general"))
        self.assertIn("benchmark_smoke,", job_block("results"))
        self.assertIn("workspace_manifest,", job_block("results"))
        self.assertEqual(WORKFLOW.read_text().count("run: just bench-smoke"), 1)

    def test_manifest_preflight_precedes_toolchain_and_does_not_compile(self):
        text = job_block("workspace_manifest")
        self.assertLess(
            text.index("python3 scripts/hepta_workspace.py"),
            text.index("dtolnay/rust-toolchain"),
        )
        self.assertIn("cargo metadata --locked --no-deps --format-version 1", text)
        self.assertNotIn("cargo check", text)
        self.assertNotIn("continue-on-error", text)

    def test_result_bindings_cover_new_required_jobs(self):
        text = job_block("results")
        self.assertIn("CHANGED_RESULT: ${{ needs.changed.result }}", text)
        self.assertIn("MANIFEST_RESULT: ${{ needs.workspace_manifest.result }}", text)
        self.assertIn("BENCHMARK_RESULT: ${{ needs.benchmark_smoke.result }}", text)

    def test_gate_shell_syntax(self):
        for job, step in (
            ("changed", "Detect changed paths (no external action)"),
            ("results", "Summarize"),
        ):
            with self.subTest(job=job):
                result = subprocess.run(
                    ["bash", "-n"],
                    input=shell_block(job, step),
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
