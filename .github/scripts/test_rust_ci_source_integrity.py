"""Execute the real CI source guards against clean and mutated Git checkouts."""

import glob
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

    def test_musl_zig_cache_never_mutates_the_qualified_checkout(self):
        for target in ("x86_64-unknown-linux-musl", "aarch64-unknown-linux-musl"):
            with self.subTest(target=target):
                tools = self.root / "fixture-tools"
                tools.mkdir(exist_ok=True)
                for name, body in {
                    "sudo": "exit 0\n",
                    "musl-gcc": "exit 99\n",
                    "zig": (
                        'cache="${ZIG_LOCAL_CACHE_DIR:-.zig-cache}"\n'
                        'mkdir -p "$cache"\n'
                        'printf "compiler cache\\n" > "$cache/used"\n'
                    ),
                }.items():
                    executable = tools / name
                    executable.write_text("#!/usr/bin/env bash\nset -eu\n" + body)
                    executable.chmod(0o755)
                tool_root = self.root / f"codex-musl-tools-{target}"
                library = tool_root / "libcap-2.75/prefix/lib/libcap.a"
                library.parent.mkdir(parents=True)
                library.touch()  # Keep this fixture offline; no package installs or downloads.
                Path(self.env["GITHUB_ENV"]).write_text("")
                cache_setup = next(
                    step["run"]
                    for step in self.workflow["jobs"]["lint_build"]["steps"]
                    if step.get("name")
                    == "Keep Zig caches outside the qualified checkout"
                )
                setup = self.execute(cache_setup)
                self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
                job_environment = dict(
                    line.split("=", 1)
                    for line in Path(self.env["GITHUB_ENV"]).read_text().splitlines()
                )
                for key in ("ZIG_LOCAL_CACHE_DIR", "ZIG_GLOBAL_CACHE_DIR"):
                    cache_path = Path(job_environment[key])
                    self.assertTrue(cache_path.is_dir())
                    self.assertTrue(cache_path.is_relative_to(self.root))
                    self.assertFalse(cache_path.is_relative_to(self.repo))
                env = {
                    **self.env,
                    **job_environment,
                    "TARGET": target,
                    "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
                }
                result = subprocess.run(
                    ["bash", str(ROOT / ".github/scripts/install-musl-build-tools.sh")],
                    cwd=self.repo,
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                environment = dict(
                    line.split("=", 1)
                    for line in Path(env["GITHUB_ENV"]).read_text().splitlines()
                )
                self.assertIn("ZIG_LOCAL_CACHE_DIR", environment)
                cache = Path(environment["ZIG_LOCAL_CACHE_DIR"])
                self.assertFalse(cache.is_relative_to(self.repo))
                self.assertTrue((cache / "used").is_file())
                # Exercise both generated compiler wrappers with the exported job environment.
                for compiler in ("CC", "CXX"):
                    result = subprocess.run(
                        [environment[compiler], "-c", "example.c"],
                        cwd=self.repo,
                        env={**env, **environment},
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                clean = self.execute(self.clean)
                self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)

    def test_source_identity_and_timings_have_separate_artifact_roots(self):
        target = self.root / "separate-cargo-target"
        timing = target / "cargo-timings/cargo-timing.html"
        timing.parent.mkdir(parents=True)
        timing.write_text("actual compiler timing")
        before = self.root / "rust-source-before.txt"
        after = self.root / "rust-source-after.txt"
        before.write_text("source before")
        after.write_text("source after")
        artifacts = []
        for step in self.workflow["jobs"]["lint_build"]["steps"]:
            if not step.get("uses", "").startswith("actions/upload-artifact@"):
                continue
            patterns = (
                step["with"]["path"]
                .replace("${{ env.CARGO_TARGET_DIR }}", str(target))
                .replace("${{ runner.temp }}", str(self.root))
            )
            files = {
                Path(path)
                for pattern in patterns.splitlines()
                for path in glob.glob(pattern, recursive=True)
            }
            if files:
                artifacts.append(files)
        self.assertCountEqual(artifacts, [{timing}, {before, after}])


if __name__ == "__main__":
    unittest.main()
