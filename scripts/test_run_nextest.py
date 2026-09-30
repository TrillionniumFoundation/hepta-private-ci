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

    def test_dependency_filter_uses_normal_metadata_and_no_tests_is_an_error(self):
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
