"""Execute the real CI source guards against clean and mutated Git checkouts."""

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "hepta_workflow_commands", ROOT / "scripts/hepta_workflow_commands.py"
)
WORKFLOW_COMMANDS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKFLOW_COMMANDS)


class RustSourceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "CI source fixture")
        self.git("config", "user.email", "ci@example.invalid")
        self.source = self.repo / "codex-rs" / "src" / "lib.rs"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("pub fn actual_product() {}\n")
        self.git("add", ".")
        self.git("commit", "-qm", "original product")
        self.env = {
            **os.environ,
            "GITHUB_WORKSPACE": str(self.repo),
            "GITHUB_SHA": self.git("rev-parse", "HEAD").strip(),
            "RUNNER_TEMP": str(self.root),
            "GITHUB_ENV": str(self.root / "environment"),
            "GITHUB_PATH": str(self.root / "path"),
        }
        self.workflow = WORKFLOW_COMMANDS.load_workflow(
            (ROOT / ".github/workflows/rust-ci-full.yml").read_text()
        )
        action = WORKFLOW_COMMANDS.load_workflow(
            (ROOT / ".github/actions/check-clean-worktree/action.yml").read_text()
        )
        self.clean = action["runs"]["steps"][0]["run"]

    def git(self, *arguments):
        return subprocess.check_output(["git", *arguments], cwd=self.repo, text=True)

    def execute(self, script):
        return subprocess.run(
            ["bash", "-c", script],
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
        )

    def guard(self, identity):
        return next(
            step["run"]
            for step in self.workflow["jobs"]["lint_build"]["steps"]
            if step.get("id") == identity
        )

    def step(self, name):
        return next(
            step
            for step in self.workflow["jobs"]["lint_build"]["steps"]
            if step.get("name") == name
        )

    def test_real_source_passes_before_and_after(self):
        for script in (
            self.guard("rust-source-before"),
            self.guard("rust-source-preflight"),
            self.clean,
            self.guard("rust-source-after"),
            self.clean,
        ):
            result = self.execute(script)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dirty_dummy_replacement_cannot_qualify(self):
        self.assertEqual(self.execute(self.guard("rust-source-before")).returncode, 0)
        self.source.write_text("// dependency cache dummy\n")
        self.assertNotEqual(self.execute(self.clean).returncode, 0)

    def test_musl_cargo_home_is_outside_the_qualified_source(self):
        result = self.execute(self.guard("rust-cargo-home"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / "rust-ci-cargo-home/config.toml").is_file())
        self.assertEqual(self.execute(self.clean).returncode, 0)

    def test_musl_zig_caches_are_outside_the_qualified_source(self):
        result = self.execute(
            self.step("Keep Zig caches outside the qualified checkout")["run"]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / "rust-ci-zig-cache/global").is_dir())
        self.assertTrue((self.root / "rust-ci-zig-cache/local").is_dir())
        self.assertEqual(self.execute(self.clean).returncode, 0)

    def test_windows_artifacts_use_separate_roots(self):
        timings = self.step("Upload Cargo timings (clippy)")["with"]["path"]
        identities = self.step("Upload qualified source identities")["with"]["path"]
        self.assertIn("CARGO_TARGET_DIR", timings)
        self.assertNotIn("runner.temp", timings)
        self.assertIn("runner.temp", identities)
        self.assertNotIn("CARGO_TARGET_DIR", identities)

    def test_untracked_product_source_cannot_qualify(self):
        self.assertEqual(self.execute(self.guard("rust-source-before")).returncode, 0)
        self.source.with_name("generated_product.rs").write_text(
            "pub fn injected() {}\n"
        )
        self.assertNotEqual(self.execute(self.clean).returncode, 0)

    def test_clean_commit_replacement_cannot_qualify(self):
        self.assertEqual(self.execute(self.guard("rust-source-before")).returncode, 0)
        self.source.write_text("// replacement committed by a build step\n")
        self.git("add", ".")
        self.git("commit", "-qm", "replace source")
        self.assertEqual(self.execute(self.clean).returncode, 0)
        self.assertNotEqual(
            self.execute(self.guard("rust-source-preflight")).returncode, 0
        )
        self.assertNotEqual(self.execute(self.guard("rust-source-after")).returncode, 0)

    def test_wrong_initial_commit_never_passes_the_guard(self):
        self.env["GITHUB_SHA"] = "0" * 40
        self.assertNotEqual(
            self.execute(self.guard("rust-source-before")).returncode, 0
        )


if __name__ == "__main__":
    unittest.main()
