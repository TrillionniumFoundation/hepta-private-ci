#!/usr/bin/env python3
"""Exercise real pinned-source imports without a model, weights or forwards."""

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import hepta_cumulative_controls as controls


ENTRY = Path(__file__).resolve().with_name("hepta_cumulative_pilot_entry.py")
PLAN = (
    ENTRY.parents[1]
    / "codex-rs/hepta-learning-artifacts/profiles/smollm2-public-initial-v2.plan.json"
)
CHAIN_SOURCE = None


class RealIsolatedImports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if CHAIN_SOURCE is None or not CHAIN_SOURCE.is_absolute():
            raise ValueError("--chain must name a real absolute Git source")
        cls.temporary = tempfile.TemporaryDirectory(prefix="hepta-pilot-import-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.chain = cls.root / "chain"
        # Reuse actual local objects. No fetch, synthetic source or Git SHA shim
        # is used; mutations below affect only this disposable sparse checkout.
        common = subprocess.check_output(
            [
                "git",
                "-C",
                str(CHAIN_SOURCE),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            text=True,
            timeout=30,
        ).strip()
        subprocess.run(
            ["git", "init", "--quiet", str(cls.chain)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        # A normal clone can request absent, unrelated promisor objects. This
        # repository has no remote and reads only real, locally available Git
        # objects through the standard alternates mechanism.
        (cls.chain / ".git/objects/info/alternates").write_text(
            str(Path(common) / "objects") + "\n"
        )
        cls.git("sparse-checkout", "set", "scripts", "formal", "config")
        cls.git("checkout", "--quiet", "--detach", controls.CHAIN_SHA)
        if cls.git("rev-parse", "HEAD").stdout.strip() != controls.CHAIN_SHA:
            raise ValueError("test did not materialize the exact original source")
        print(
            "Import-only source "
            + controls.CHAIN_SHA
            + "; entry SHA256 "
            + hashlib.sha256(ENTRY.read_bytes()).hexdigest(),
            flush=True,
        )

    @classmethod
    def git(cls, *args):
        try:
            return subprocess.run(
                ["git", "-C", str(cls.chain), *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.CalledProcessError as error:
            raise RuntimeError(error.stderr) from error

    def environment(self):
        env = os.environ.copy()
        for name in (
            "PYTHONPATH",
            "PYTHONHOME",
            "PYTHONUSERBASE",
            "PYTHONDONTWRITEBYTECODE",
            "HEPTA_PUBLIC_INITIAL_RUNTIME_SNAPSHOT",
        ):
            env.pop(name, None)
        return env

    def entry(self, args=None, *, flags=("-I", "-B"), cwd=None, env=None):
        return subprocess.run(
            [
                sys.executable,
                *flags,
                str(ENTRY),
                "--chain",
                str(self.chain),
                *(args if args is not None else ["_child", "--help"]),
            ],
            cwd=cwd,
            env=self.environment() if env is None else env,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def evaluation(
        self, *, phase="evaluate", role="fresh-budget-matched-lora", plan=PLAN
    ):
        return [
            "_child",
            "--materials",
            str(self.root / "no-model"),
            "--output",
            str(self.root / "must-not-create-output"),
            "--plan",
            str(plan),
            "--phase",
            phase,
            "--role",
            role,
            "--artifact",
            str(self.root / "no-weights"),
        ]

    def rejected(self, result, message):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(message, result.stderr)
        self.assertFalse((self.root / "must-not-create-output").exists())

    def test_original_isolated_entry_reproduces_the_sibling_import_failure(self):
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(self.chain / "scripts/llm_runtime_pilot.py"),
                "_child",
                "--help",
            ],
            env=self.environment(),
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No module named 'llm_runtime_parent_step'", result.stderr)

    def test_real_original_parser_imports_with_and_without_path_pollution(self):
        poison = self.root / "untrusted-imports"
        poison.mkdir()
        marker = poison / "executed"
        payload = (
            "from pathlib import Path\nPath("
            + repr(str(marker))
            + ").write_text('executed')\n"
        )
        for name in (
            "llm_runtime_pilot.py",
            "llm_runtime_parent_step.py",
            "sitecustomize.py",
        ):
            (poison / name).write_text(payload)
        env = self.environment()
        env["PYTHONPATH"] = str(poison)
        for polluted in (False, True):
            with self.subTest(polluted=polluted):
                result = self.entry(
                    cwd=poison if polluted else self.root, env=env if polluted else None
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("--parent-step-input", result.stdout)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(marker.exists())

    def test_isolation_and_no_bytecode_flags_are_required(self):
        for flags in (("-B",), ("-I",)):
            with self.subTest(flags=flags):
                self.rejected(
                    self.entry(flags=flags), "isolated Python with -I -B is required"
                )

    def test_a_different_real_commit_is_rejected(self):
        try:
            self.git(
                "-c",
                "user.name=Import control",
                "-c",
                "user.email=control.invalid@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--quiet",
                "--allow-empty",
                "-m",
                "wrong-source negative control",
            )
            self.rejected(self.entry(), "exact original Chain source required")
        finally:
            self.git("reset", "--quiet", "--hard", controls.CHAIN_SHA)

    def test_changed_tracked_sibling_is_rejected_before_execution(self):
        path = self.chain / "scripts/llm_runtime_parent_step.py"
        original = path.read_bytes()
        marker = self.root / "changed-source-executed"
        try:
            path.write_bytes(
                original
                + (
                    "\nfrom pathlib import Path\nPath("
                    + repr(str(marker))
                    + ").write_text('executed')\n"
                ).encode()
            )
            result = self.entry()
            self.rejected(result, "CalledProcessError")
            self.assertFalse(marker.exists())
        finally:
            path.write_bytes(original)

    def test_ignored_untracked_package_cannot_shadow_the_checked_sibling(self):
        package = self.chain / "scripts/llm_runtime_parent_step"
        package.mkdir()
        exclude = self.chain / ".git/info/exclude"
        old_exclude = exclude.read_bytes()
        marker = self.root / "untracked-source-executed"
        try:
            (package / "__init__.py").write_text(
                "from pathlib import Path\nPath("
                + repr(str(marker))
                + ").write_text('executed')\n"
            )
            exclude.write_bytes(old_exclude + b"\nscripts/llm_runtime_parent_step/\n")
            self.git("diff", "--exit-code", "HEAD", "--", "scripts", "formal", "config")
            self.rejected(self.entry(), "untracked fixed source is not importable")
            self.assertFalse(marker.exists())
        finally:
            exclude.write_bytes(old_exclude)
            shutil.rmtree(package)

    def test_other_commands_phases_and_roles_do_not_reach_the_model(self):
        self.rejected(
            self.entry(["run"]), "only the original evaluator child is allowed"
        )
        for args in (self.evaluation(phase="train"), self.evaluation(role="candidate")):
            with self.subTest(args=args):
                self.rejected(
                    self.entry(args), "only cumulative control evaluation is allowed"
                )

    def test_semantically_equal_but_unpinned_plan_bytes_are_rejected(self):
        changed = self.root / "changed-plan.json"
        changed.write_bytes(PLAN.read_bytes() + b"\n")
        self.rejected(
            self.entry(self.evaluation(plan=changed)),
            "unchanged evaluator ten-step plan bytes",
        )

    def test_actual_evaluation_still_requires_the_cold_runtime_snapshot(self):
        self.rejected(
            self.entry(self.evaluation()), "HEPTA_PUBLIC_INITIAL_RUNTIME_SNAPSHOT"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--chain", type=Path, required=True)
    arguments, remaining = parser.parse_known_args()
    CHAIN_SOURCE = arguments.chain
    unittest.main(argv=[sys.argv[0], *remaining])
