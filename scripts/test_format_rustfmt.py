"""Exercise scoped formatting with the host's real rustfmt and Cargo tools."""

import importlib.util
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "repo_format_rustfmt_target", Path(__file__).with_name("format.py")
)
FMT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = FMT
SPEC.loader.exec_module(FMT)


class RealRustfmtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for tool in ("rustfmt", "cargo"):
            subprocess.run([tool, "--version"], check=True, capture_output=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="formatter space' ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        patcher = patch.object(FMT, "REPO_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.directory = self.root / "codex-rs" / "owner space'"
        self.directory.mkdir(parents=True)

    def write(self, name, content):
        path = self.directory / name
        path.write_bytes(content.encode("utf-8"))
        return path

    def sources(self):
        return {path.name: path.read_bytes() for path in self.directory.glob("*.rs")}

    def group(self, paths, *, check):
        (group,) = FMT.scoped_formatter_groups(
            [path.relative_to(self.root).as_posix() for path in paths], check=check
        )
        return group

    def run_group(self, group):
        original_run = subprocess.run
        with patch.object(FMT.subprocess, "run", wraps=original_run) as runner:
            result = FMT.run_formatter_group(group)
        return result, [
            (call.args[0], call.kwargs["cwd"]) for call in runner.call_args_list
        ]

    def test_check_batches_quoted_paths_and_leaves_unselected_module_untouched(self):
        first = self.write("lib.rs", "mod unselected;\n\npub fn first() {}\n")
        second = self.write("选中 space'.rs", "pub fn second() {}\n")
        self.write("unselected.rs", "pub fn broken(\n")
        before = self.sources()
        group = self.group([first, second], check=True)

        result, calls = self.run_group(group)

        self.assertEqual(result.returncode, 0, result.output)
        self.assertEqual(
            calls, [((*group.commands[0].args, str(second)), self.directory)]
        )
        self.assertEqual(self.sources(), before)

    def test_check_preserves_real_format_and_parse_failures_without_writing(self):
        second = self.write("second.rs", "pub fn second() {}\n")
        self.write("unselected.rs", "pub fn unselected(\n")
        for source in ("pub fn first( ) {}\n", "pub fn first(\n"):
            with self.subTest(source=source):
                first = self.write("first.rs", source)
                before = self.sources()
                group = self.group([first, second], check=True)
                command = group.commands[0]
                baseline = subprocess.run(
                    command.args, cwd=command.cwd, capture_output=True
                )

                result, calls = self.run_group(group)

                self.assertNotEqual(baseline.returncode, 0)
                self.assertEqual(result.returncode, baseline.returncode)
                self.assertEqual(len(calls), 1)
                self.assertEqual(self.sources(), before)

    def test_fix_stops_at_parse_failure_before_modifying_later_files(self):
        first = self.write("a.rs", "mod unselected;\n\npub fn first( ) {}\n")
        broken = self.write("b.rs", "pub fn broken(\n")
        later = self.write("c.rs", "pub fn later( ) {}\n")
        self.write("unselected.rs", "pub fn unselected(\n")
        expected = self.sources()
        expected["a.rs"] = b"mod unselected;\n\npub fn first() {}\n"
        group = self.group([first, broken, later], check=False)

        result, calls = self.run_group(group)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            calls, [(command.args, command.cwd) for command in group.commands[:2]]
        )
        self.assertEqual(self.sources(), expected)

    def test_real_check_splits_long_unicode_arguments_without_losing_sources(self):
        paths = [
            self.write(f"{'界' * 40}{i:03}.rs", "pub fn entry() {}\n")
            for i in range(60)
        ]
        before = self.sources()
        group = self.group(paths, check=True)

        result, calls = self.run_group(group)

        self.assertEqual(result.returncode, 0, result.output)
        self.assertGreater(len(calls), 1)
        self.assertLess(len(calls), len(paths))
        self.assertEqual(
            [source for args, _ in calls for source in args[args.index("--") + 1 :]],
            [command.args[-1] for command in group.commands],
        )
        for args, cwd in calls:
            self.assertEqual(cwd, self.directory)
            self.assertLessEqual(
                sum(2 * len(os.fsencode(arg)) + 3 for arg in args), 16000
            )
        self.assertEqual(self.sources(), before)

    def test_full_rust_group_keeps_one_real_cargo_fmt_invocation(self):
        workspace = self.root / "codex-rs"
        (workspace / "Cargo.toml").write_bytes(
            b'[workspace]\nmembers = ["example"]\nresolver = "2"\n'
        )
        package = workspace / "example"
        (package / "src").mkdir(parents=True)
        (package / "Cargo.toml").write_bytes(
            b'[package]\nname = "format-fixture"\nversion = "0.0.0"\nedition = "2021"\n'
        )
        source = package / "src" / "lib.rs"
        source.write_bytes(b"pub fn entry() {}\n")
        group = FMT.rust_formatter_group(check=True)

        result, calls = self.run_group(group)

        self.assertEqual(result.returncode, 0, result.output)
        self.assertEqual(calls, [(group.commands[0].args, workspace)])
        self.assertEqual(source.read_bytes(), b"pub fn entry() {}\n")


if __name__ == "__main__":
    unittest.main()
