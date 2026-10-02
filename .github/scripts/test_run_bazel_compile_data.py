"""Check fleet's include_str! input in a minimal declared-input compiler sandbox."""

import ast
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("codex-rs/hepta-fleet/src/module_catalog.rs")


def resolve_rustc():
    # Resolve an already installed compiler, never compile through the ambient
    # rustup proxy (which may synchronize an unrelated default toolchain).
    if compiler := os.environ.get("RUSTC"):
        return compiler
    channel = tomllib.loads((ROOT / "codex-rs/rust-toolchain.toml").read_text())[
        "toolchain"
    ]["channel"]
    result = subprocess.run(
        ["rustup", "which", "--toolchain", channel, "rustc"],
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    compiler = result.stdout.strip()
    if not compiler:
        raise RuntimeError("rustup returned no installed compiler path")
    return compiler


def calls(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


class FleetCompileDataTests(unittest.TestCase):
    def compile_fixture(self, *, omit_catalog):
        declarations = calls(
            ROOT / "codex-rs/hepta-fleet/BUILD.bazel", "codex_rust_crate"
        )
        self.assertEqual(len(declarations), 1)
        keywords = {entry.arg: entry.value for entry in declarations[0].keywords}
        labels = (
            ast.literal_eval(keywords["compile_data"])
            if "compile_data" in keywords
            else []
        )
        include = re.search(r'include_str!\("([^"]+)"\)', (ROOT / SOURCE).read_text())
        self.assertIsNotNone(include)
        relative = include.group(1)
        required = (ROOT / SOURCE.parent / relative).resolve().relative_to(ROOT)
        exports = calls(ROOT / "BUILD.bazel", "exports_files")
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            source = sandbox / SOURCE
            source.parent.mkdir(parents=True)
            source.write_text(
                f'pub const CATALOG: &str = include_str!("{relative}");\n'
            )
            for label in labels:
                self.assertTrue(
                    label.startswith("//:"),
                    "fixture expects an explicit root file label",
                )
                path = Path(label[3:])
                self.assertEqual(
                    path,
                    required,
                    "fleet must not receive unrelated compile-time inputs",
                )
                export = next(
                    (
                        call
                        for call in exports
                        if path.as_posix() in ast.literal_eval(call.args[0])
                    ),
                    None,
                )
                self.assertIsNotNone(
                    export, "cross-package input must be explicitly exported"
                )
                visibility = next(
                    entry.value
                    for entry in export.keywords
                    if entry.arg == "visibility"
                )
                self.assertEqual(
                    ast.literal_eval(visibility), ["//codex-rs/hepta-fleet:__pkg__"]
                )
                if omit_catalog:
                    continue
                destination = sandbox / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / path, destination)
            return subprocess.run(
                [
                    resolve_rustc(),
                    "--crate-type=lib",
                    "--emit=metadata",
                    str(source),
                    "--out-dir",
                    str(sandbox),
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )

    def test_declared_input_resolves_actual_include_path(self):
        result = self.compile_fixture(omit_catalog=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_declared_input_fails_compilation(self):
        result = self.compile_fixture(omit_catalog=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MODULES.json", result.stderr)


class CompilerSelectionTests(unittest.TestCase):
    def test_resolves_installed_pinned_compiler_without_installing(self):
        with mock.patch.dict(os.environ, {"RUSTUP_TOOLCHAIN": "unrelated"}, clear=True):
            with mock.patch.object(subprocess, "run") as run:
                run.return_value.stdout = "C:\\toolchains\\1.95.0\\rustc.exe\n"
                self.assertEqual(resolve_rustc(), "C:\\toolchains\\1.95.0\\rustc.exe")
                channel = tomllib.loads(
                    (ROOT / "codex-rs/rust-toolchain.toml").read_text()
                )["toolchain"]["channel"]
                run.assert_called_once_with(
                    ["rustup", "which", "--toolchain", channel, "rustc"],
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=30,
                )

    def test_explicit_compiler_does_not_launch_rustup(self):
        with mock.patch.dict(os.environ, {"RUSTC": "custom compiler.exe"}):
            with mock.patch.object(subprocess, "run") as run:
                self.assertEqual(resolve_rustc(), "custom compiler.exe")
                run.assert_not_called()

    def test_missing_pinned_compiler_fails_without_ambient_fallback(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(subprocess, "run") as run:
                run.side_effect = subprocess.CalledProcessError(1, "rustup")
                with self.assertRaises(subprocess.CalledProcessError):
                    resolve_rustc()
                self.assertEqual(run.call_count, 1)

    def test_every_ci_wrapper_consumer_installs_pinned_compiler_first(self):
        channel = tomllib.loads((ROOT / "codex-rs/rust-toolchain.toml").read_text())[
            "toolchain"
        ]["channel"]
        consumers = 0
        for name in ("repo-checks.yml", "bazel.yml"):
            # Jobs are top-level YAML entries indented exactly two spaces.
            jobs = re.split(
                r"(?m)^  [a-zA-Z0-9_-]+:\s*$",
                (ROOT / ".github/workflows" / name).read_text(),
            )
            for job in jobs:
                if "-p 'test_run_bazel*.py'" not in job:
                    continue
                consumers += 1
                before = job.split("-p 'test_run_bazel*.py'", 1)[0]
                self.assertRegex(before, r"uses: dtolnay/rust-toolchain@")
                self.assertIn(f"toolchain: {channel}", before)
        self.assertEqual(consumers, 3)

    def test_compile_timeout_is_enforced_and_propagated(self):
        with mock.patch.dict(os.environ, {"RUSTC": "installed-rustc"}):
            with mock.patch.object(subprocess, "run") as run:
                run.side_effect = subprocess.TimeoutExpired("installed-rustc", 30)
                with self.assertRaises(subprocess.TimeoutExpired):
                    FleetCompileDataTests().compile_fixture(omit_catalog=False)
                self.assertEqual(run.call_args.args[0][0], "installed-rustc")
                self.assertEqual(run.call_args.kwargs["timeout"], 30)
                self.assertIn("--emit=metadata", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
