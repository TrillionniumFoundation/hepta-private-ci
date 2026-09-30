"""Exercise scoped test execution against a real, dependency-free workspace."""

import contextlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "run_nextest", Path(__file__).with_name("run-nextest.py")
)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class FilterMetadataStrategyTests(unittest.TestCase):
    def test_graph_words_inside_matchers_do_not_become_dependencies(self):
        for expression in (
            "test(deps) | test(rdeps)",
            r"test(/deps\(opaque\)|rdeps\(opaque\)/) & !test(/never/)",
            r"test(~left\)right) | test(#a\,b*)",
            r"test(=unicode\u{4e00})",
            "not (package(hepta-nextest-fixture) - test(absent)) + none()",
        ):
            with self.subTest(expression=expression):
                self.assertTrue(RUNNER.graph_free_filter(expression))

    def test_graph_expansion_unknown_and_opaque_syntax_keep_full_metadata(self):
        for expression in (
            "deps(hepta-nextest-fixture)",
            "test(actual_test) | rdeps(hepta-nextest-fixture)",
            "default()",
            "future_predicate(actual_test)",
            "test(actual_test))",
            "test(actual_test) &",
            "test(/unterminated)",
            r"test(invalid\q)",
            r"test(invalid\u{110000})",
            "test(a,b)",
            "!" * 1000 + "all()",
            "(" * 1000 + "all()" + ")" * 1000,
            "test(" + "a" * 16385 + ")",
        ):
            with self.subTest(expression=expression):
                self.assertFalse(RUNNER.graph_free_filter(expression))

    def test_filter_flag_forms_multiple_filters_and_test_arguments(self):
        for args in (
            ["-E", "test(actual_test)"],
            ["-Etest(actual_test)"],
            ["-E=test(actual_test)"],
            ["--filterset", "test(actual_test)"],
            ["--filterset=test(actual_test)"],
        ):
            with self.subTest(args=args):
                self.assertEqual(RUNNER.filtersets(args), ["test(actual_test)"])
        self.assertEqual(RUNNER.filtersets(["--", "-E", "deps(opaque)"]), [])
        self.assertIsNone(RUNNER.filtersets(["-E"]))
        self.assertIsNone(RUNNER.filtersets(["--filterset", "--"]))
        self.assertEqual(
            RUNNER.filtersets(["-Etest(actual_test)", "--filterset=deps(opaque)"]),
            ["test(actual_test)", "deps(opaque)"],
        )


@unittest.skipUnless(
    shutil.which("cargo") and shutil.which("cargo-nextest"),
    "requires Cargo and nextest",
)
class ScopedNextestTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="hepta-nextest-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "src").mkdir()
        (self.root / "Cargo.toml").write_text(
            '[package]\nname="hepta-nextest-fixture"\nversion="0.1.0"\nedition="2024"\n[features]\nnegative=[]\n[workspace]\n'
        )
        (self.root / "src/lib.rs").write_text(
            '#[test]\nfn actual_test() { assert!(!cfg!(feature = "negative")); }\n'
        )
        self.commands = []
        actual_call = subprocess.call

        def observe(command, **kwargs):
            self.commands.append(command[:])
            with (self.root / "output.log").open("ab") as output:
                kwargs.setdefault("stdout", output)
                kwargs.setdefault("stderr", output)
                return actual_call(command, **kwargs)

        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.chdir(self.root))
        self.stack.enter_context(
            patch.dict(
                os.environ,
                {
                    "CARGO_TARGET_DIR": str(self.root / "target"),
                    "NEXTEST_PROFILE": "default",
                    "HEPTA_NEXTTEST_FULL_METADATA": "0",
                },
            )
        )
        self.stack.enter_context(
            patch.object(RUNNER.subprocess, "call", side_effect=observe)
        )

    def test_scoped_test_reaches_real_nextest_and_propagates_feature_failure(self):
        self.assertEqual(
            RUNNER.run(["-p", "hepta-nextest-fixture", "--offline", "--lib"]), 0
        )
        self.assertIn("--cargo-metadata", self.commands[-1])
        self.assertIn("1 test run: 1 passed", (self.root / "output.log").read_text())
        self.assertNotEqual(
            RUNNER.run(
                [
                    "-p",
                    "hepta-nextest-fixture",
                    "--offline",
                    "--lib",
                    "--features",
                    "negative",
                ]
            ),
            0,
        )
        self.assertIn("1 failed", (self.root / "output.log").read_text())

    def test_pure_test_filter_uses_scoped_metadata_and_no_tests_is_an_error(self):
        self.assertNotEqual(
            RUNNER.run(
                [
                    "-p",
                    "hepta-nextest-fixture",
                    "--offline",
                    "--lib",
                    "-E",
                    "test(absent)",
                ]
            ),
            0,
        )
        self.assertIn("--cargo-metadata", self.commands[-1])
        self.assertIn("no tests to run", (self.root / "output.log").read_text())

    def test_pure_filters_preserve_real_selection_and_feature_failure(self):
        for option in (
            ["-E", "package(hepta-nextest-fixture) & test(actual_test)"],
            ["-Etest(/actual_test|deps\\(opaque\\)/)"],
            ["-E=test(actual_test)"],
            ["--filterset=test(actual_test) & !test(absent)"],
        ):
            with self.subTest(option=option):
                args = ["-p", "hepta-nextest-fixture", "--offline", "--lib", *option]
                self.assertEqual(RUNNER.run(args), 0)
                self.assertIn("--cargo-metadata", self.commands[-1])
                with patch.dict(os.environ, {"HEPTA_NEXTTEST_FULL_METADATA": "1"}):
                    self.assertEqual(RUNNER.run(args), 0)
                self.assertNotIn("--cargo-metadata", self.commands[-1])
        self.assertEqual(
            (self.root / "output.log").read_text().count("1 test run: 1 passed"), 8
        )
        self.assertNotEqual(
            RUNNER.run(
                [
                    "-p",
                    "hepta-nextest-fixture",
                    "--offline",
                    "--features",
                    "negative",
                    "-Etest(actual_test)",
                ]
            ),
            0,
        )
        self.assertIn("--cargo-metadata", self.commands[-1])
        self.assertIn("1 failed", (self.root / "output.log").read_text())

    def test_dependency_opaque_and_config_filters_keep_normal_metadata(self):
        for expression, expected_success in (
            ("deps(hepta-nextest-fixture)", True),
            ("rdeps(hepta-nextest-fixture) & test(actual_test)", True),
            ("default()", True),
            ("future_predicate(actual_test)", False),
            ("test(actual_test))", False),
        ):
            with self.subTest(expression=expression):
                status = RUNNER.run(
                    [
                        "-p",
                        "hepta-nextest-fixture",
                        "--offline",
                        "--lib",
                        "-E",
                        expression,
                    ]
                )
                self.assertEqual(status == 0, expected_success)
                self.assertNotIn("--cargo-metadata", self.commands[-1])
        config = self.root / ".config/nextest.toml"
        config.parent.mkdir()
        config.write_text(
            '[profile.default]\ndefault-filter = "deps(hepta-nextest-fixture)"\n'
        )
        self.assertEqual(
            RUNNER.run(
                [
                    "-p",
                    "hepta-nextest-fixture",
                    "--offline",
                    "-Etest(actual_test)",
                ]
            ),
            0,
        )
        self.assertNotIn("--cargo-metadata", self.commands[-1])

    def test_explicit_manifest_preserves_nextest_workspace_selection(self):
        for manifest_option in (
            ["--manifest-path", str(self.root / "Cargo.toml")],
            [f"--manifest-path={self.root / 'Cargo.toml'}"],
        ):
            self.assertEqual(
                RUNNER.run(
                    ["-p", "hepta-nextest-fixture", "--offline", *manifest_option]
                ),
                0,
            )
            self.assertNotIn("--cargo-metadata", self.commands[-1])

    def test_reused_metadata_is_forwarded_and_full_path_can_be_forced(self):
        metadata = self.root / "provided.json"
        with metadata.open("wb") as output:
            self.assertEqual(
                subprocess.call(
                    [
                        "cargo",
                        "metadata",
                        "--no-deps",
                        "--offline",
                        "--format-version=1",
                    ],
                    stdout=output,
                ),
                0,
            )
        self.assertEqual(
            RUNNER.run(
                [
                    "-p",
                    "hepta-nextest-fixture",
                    "--offline",
                    "--cargo-metadata",
                    str(metadata),
                    "--",
                    "actual_test",
                    "--exact",
                ]
            ),
            0,
        )
        self.assertEqual(self.commands[-1].count("--cargo-metadata"), 1)
        with patch.dict(os.environ, {"HEPTA_NEXTTEST_FULL_METADATA": "1"}):
            self.assertEqual(
                RUNNER.run(["-p", "hepta-nextest-fixture", "--offline"]), 0
            )
        self.assertNotIn("--cargo-metadata", self.commands[-1])


if __name__ == "__main__":
    unittest.main()
