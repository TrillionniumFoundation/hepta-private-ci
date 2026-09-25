"""Exact-tree regressions: opaque inputs are not limited to documentation."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import hepta_ci_dependencies as ci


class OpaqueInputSelectionTests(unittest.TestCase):
    def setUp(self):
        self.owners = {
            f"codex-rs/{name}": name
            for name in (
                "producer",
                "reader",
                "host",
                "test_host",
                "test_downstream",
                "other",
            )
        }
        self.edges = frozenset(
            {
                ("reader", "host", False),
                ("reader", "test_host", True),
                ("test_host", "test_downstream", False),
            }
        )
        self.plain = ci.Graph(self.owners, self.edges)
        self.opaque = ci.Graph(
            self.owners, self.edges, opaque_input_consumers=frozenset({"reader"})
        )

    def test_owned_json_also_selects_opaque_reader_and_dependents(self):
        result = ci.select_packages(
            ["codex-rs/producer/data/policy.json"], self.opaque, self.opaque
        )
        self.assertEqual(
            result["packages"], ["host", "producer", "reader", "test_host"]
        )
        self.assertFalse(result["full_workspace"])

    def test_old_and_new_opaque_consumers_are_both_preserved(self):
        for before, after in ((self.opaque, self.plain), (self.plain, self.opaque)):
            with self.subTest(before=before.opaque_input_consumers):
                result = ci.select_packages(
                    ["codex-rs/producer/src/fragment.rs"], before, after
                )
                self.assertIn("reader", result["packages"])
                self.assertIn("host", result["packages"])
                self.assertNotIn("test_downstream", result["packages"])

    def test_empty_diff_does_not_select_opaque_consumers(self):
        self.assertEqual(
            ci.select_packages([], self.opaque, self.opaque)["packages"], []
        )

    def test_known_graph_stays_local(self):
        result = ci.select_packages(
            ["codex-rs/producer/data/policy.json"], self.plain, self.plain
        )
        self.assertEqual(result["packages"], ["producer"])
        self.assertFalse(result["full_workspace"])

    def test_unknown_input_still_forces_full_fallback(self):
        result = ci.select_packages(
            ["external/unclaimed.bin"], self.opaque, self.opaque
        )
        self.assertTrue(result["full_workspace"])
        self.assertEqual(result["packages"], sorted(self.owners.values()))

    def test_removed_opaque_package_is_not_a_cargo_target(self):
        after = ci.Graph(
            {p: name for p, name in self.owners.items() if name != "reader"}, self.edges
        )
        result = ci.select_packages(
            ["codex-rs/producer/data/policy.json"], self.opaque, after
        )
        self.assertIn("host", result["packages"])
        self.assertNotIn("reader", result["packages"])


class ExactTreeOpaqueInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "CI input regression")
        self.git("config", "user.email", "ci-input@example.invalid")
        self.write(
            "codex-rs/Cargo.toml",
            '[workspace]\nmembers=["producer","reader","host","other"]\n',
        )
        for name in ("producer", "reader", "host", "other"):
            self.write(
                f"codex-rs/{name}/Cargo.toml",
                f'[package]\nname="{name}"\nversion="0.1.0"\n',
            )
            self.write(f"codex-rs/{name}/src/lib.rs", "pub fn value() -> u32 { 1 }\n")
        with (self.root / "codex-rs/host/Cargo.toml").open("a") as stream:
            stream.write('[dependencies]\nreader={path="../reader"}\n')
        self.input = "codex-rs/producer/data/policy.json"
        self.write(self.input, '{"revision":1}\n')

    def git(self, *args):
        return ci.git(self.root, *args).decode().strip()

    def write(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def change_input(self, base):
        self.write(self.input, '{"revision":2}\n')
        return ci.plan(self.root, base, self.commit())

    def test_computed_include_in_another_package_is_not_missed(self):
        self.write(
            "codex-rs/reader/src/lib.rs",
            'pub const POLICY: &str = include_str!(concat!(env!("CARGO_MANIFEST_DIR"), '
            '"/../producer/data/policy.json"));\n',
        )
        base = self.commit()
        result = self.change_input(base)
        self.assertEqual(result["packages"], ["host", "producer", "reader"])
        self.assertFalse(result["full_workspace"])

    def test_literal_include_is_still_precise(self):
        self.write(
            "codex-rs/reader/src/lib.rs",
            'pub const POLICY: &str = include_str!("../../producer/data/policy.json");\n',
        )
        self.assertEqual(
            self.change_input(self.commit())["packages"], ["host", "producer", "reader"]
        )

    def test_declared_build_script_reads_are_opaque_without_execution(self):
        with (self.root / "codex-rs/reader/Cargo.toml").open("a") as stream:
            stream.write('build="generate.rs"\n')
        self.write(
            "codex-rs/reader/generate.rs",
            'fn main() { let _ = std::fs::read("../producer/data/policy.json"); }\n',
        )
        result = self.change_input(self.commit())
        self.assertEqual(result["packages"], ["host", "producer", "reader"])
        self.assertFalse(result["full_workspace"])

    def test_automatic_build_script_is_also_an_opaque_consumer(self):
        self.write(
            "codex-rs/reader/build.rs",
            'fn main() { let _ = std::fs::read("../producer/data/policy.json"); }\n',
        )
        self.assertEqual(
            self.change_input(self.commit())["packages"], ["host", "producer", "reader"]
        )

    def test_build_false_does_not_add_a_build_script_consumer(self):
        with (self.root / "codex-rs/reader/Cargo.toml").open("a") as stream:
            stream.write("build=false\n")
        self.write("codex-rs/reader/build.rs", "fn main() {}\n")
        self.assertEqual(self.change_input(self.commit())["packages"], ["producer"])

    def test_literal_reader_does_not_expand_unrelated_changes(self):
        self.write(
            "codex-rs/reader/src/lib.rs",
            'pub const POLICY: &str = include_str!("../../producer/data/policy.json");\n',
        )
        base = self.commit()
        self.write("codex-rs/other/src/lib.rs", "pub fn value() -> u32 { 2 }\n")
        self.assertEqual(ci.plan(self.root, base, self.commit())["packages"], ["other"])

    def test_explicit_build_script_outside_package_is_not_treated_as_prose(self):
        with (self.root / "codex-rs/reader/Cargo.toml").open("a") as stream:
            stream.write('build="../../docs/generator.md"\n')
        self.write("docs/generator.md", "fn main() {}\n")
        self.assertEqual(
            self.change_input(self.commit())["packages"], ["host", "producer", "reader"]
        )

    def test_no_diff_with_build_script_requires_no_native_work(self):
        self.write("codex-rs/reader/build.rs", "fn main() {}\n")
        base = self.commit()
        self.assertEqual(ci.plan(self.root, base, base)["packages"], [])


@unittest.skipUnless(shutil.which("bash"), "workflow shell regressions require Bash")
class PreflightDiagnosticTests(unittest.TestCase):
    def run_preflight(self, fail_suite):
        workflow = (
            Path(__file__).resolve().parents[1] / ".github/workflows/"
            "hepta-repository-integrity.yml"
        ).read_text(encoding="utf-8")
        step = workflow.split(
            "- name: Exercise preflight and source-identity regressions", 1
        )[1]
        block = step.split("run: |", 1)[1].split("- name:", 1)[0]
        script = "\n".join(
            line[10:] for line in block.splitlines() if line.startswith(" " * 10)
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "python3"
            executable.write_text(
                '#!/bin/sh\necho "$*" >> "$CALL_LOG"\n'
                'case "$*" in *"$FAIL_SUITE"*) exit 7 ;; esac\nexit 0\n',
                encoding="utf-8",
            )
            executable.chmod(0o700)
            log = root / "calls.log"
            env = dict(
                os.environ,
                PATH=str(root) + os.pathsep + os.environ.get("PATH", ""),
                CALL_LOG=str(log),
                FAIL_SUITE=fail_suite,
            )
            result = subprocess.run(
                ["bash", "-c", script],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            calls = log.read_text(encoding="utf-8").splitlines()
        return result, calls

    def assert_all_suites(self, calls):
        observed = [line.split()[-1] for line in calls]
        mandatory = {
            "test_hepta_integrity_checkout.py",
            "test_hepta_workspace.py",
            "test_hepta_implementation_identity.py",
            "test_hepta_ci_dependency_scaling.py",
            "test_hepta_ci_nested_inputs.py",
            "test_hepta_ci_opaque_inputs.py",
        }
        self.assertEqual(len(observed), len(set(observed)), "duplicate suite execution")
        self.assertTrue(mandatory <= set(observed), set(observed))
        scripts = Path(__file__).resolve().parent
        for name in observed:
            self.assertEqual(Path(name).name, name)
            self.assertTrue((scripts / name).is_file(), name)

    def test_all_cheap_suites_run_when_successful(self):
        result, calls = self.run_preflight("no-matching-suite")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_all_suites(calls)

    def test_early_middle_and_last_failures_are_not_hidden(self):
        baseline, expected_calls = self.run_preflight("no-matching-suite")
        self.assertEqual(baseline.returncode, 0, baseline.stderr)
        self.assert_all_suites(expected_calls)
        suites = [line.split()[-1] for line in expected_calls]
        for suite in (suites[0], suites[len(suites) // 2], suites[-1]):
            with self.subTest(suite=suite):
                result, calls = self.run_preflight(suite)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, expected_calls)


if __name__ == "__main__":
    unittest.main()
