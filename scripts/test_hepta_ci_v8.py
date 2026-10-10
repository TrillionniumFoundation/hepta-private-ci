#!/usr/bin/env python3
"""Behavioral checks for V8 host discovery and fail-closed CI environment writes."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hepta_ci_v8

ROOT = Path(__file__).resolve().parents[1]


class V8EnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / "environment"
        self.output.write_text("EXISTING=preserved\n", encoding="utf-8")
        self.environment = mock.patch.dict(os.environ, {"CODEX_REPO_ROOT": str(ROOT)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.host = mock.patch.object(
            hepta_ci_v8.subprocess,
            "check_output",
            return_value="rustc 1.95.0\nhost: aarch64-unknown-linux-gnu\n",
        )
        self.host_mock = self.host.start()
        self.addCleanup(self.host.stop)
        self.resolver = mock.patch("codex_package.v8.resolve_codex_v8_cargo_env")
        self.resolve = self.resolver.start()
        self.addCleanup(self.resolver.stop)
        self.resolve.return_value = {
            "RUSTY_V8_ARCHIVE": "/tmp/verified artifacts/v8.a.gz",
            "RUSTY_V8_SRC_BINDING_PATH": "/tmp/verified artifacts/binding.rs",
        }

    def test_host_selects_matching_pair_and_preserves_existing_environment(
        self,
    ) -> None:
        hepta_ci_v8.configure_v8(ROOT, self.output)
        self.assertEqual(
            self.resolve.call_args.args[0].target, "aarch64-unknown-linux-gnu"
        )
        self.assertEqual(
            self.output.read_text(encoding="utf-8"),
            "EXISTING=preserved\n"
            "RUSTY_V8_ARCHIVE=/tmp/verified artifacts/v8.a.gz\n"
            "RUSTY_V8_SRC_BINDING_PATH=/tmp/verified artifacts/binding.rs\n",
        )
        self.host_mock.assert_called_once_with(
            ["rustc", "-vV"], cwd=ROOT / "codex-rs", text=True, timeout=60
        )

    def test_unknown_missing_or_ambiguous_host_never_resolves_or_writes(self) -> None:
        for version in ("rustc 1.95.0", "host: unsupported", "host: x\nhost: y"):
            with self.subTest(version=version):
                self.host_mock.return_value = version
                with self.assertRaisesRegex(RuntimeError, "supported Rust host"):
                    hepta_ci_v8.configure_v8(ROOT, self.output)
        self.resolve.assert_not_called()
        self.assertEqual(self.output.read_text(), "EXISTING=preserved\n")

    def test_verified_override_or_source_build_does_not_replace_environment(
        self,
    ) -> None:
        self.resolve.return_value = {}
        hepta_ci_v8.configure_v8(ROOT, self.output)
        self.assertEqual(self.output.read_text(), "EXISTING=preserved\n")

    def test_resolution_failure_leaves_environment_unchanged(self) -> None:
        self.resolve.side_effect = RuntimeError("checksum mismatch")
        with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
            hepta_ci_v8.configure_v8(ROOT, self.output)
        self.assertEqual(self.output.read_text(), "EXISTING=preserved\n")

    def test_partial_pair_and_environment_injection_are_rejected_before_writing(
        self,
    ) -> None:
        for overrides in (
            {"RUSTY_V8_ARCHIVE": "/tmp/archive"},
            {"OTHER": "x"},
            {
                "RUSTY_V8_ARCHIVE": "/tmp/archive",
                "RUSTY_V8_SRC_BINDING_PATH": "x\nOTHER=1",
            },
            {"RUSTY_V8_ARCHIVE": "", "RUSTY_V8_SRC_BINDING_PATH": "x"},
        ):
            with self.subTest(overrides=overrides):
                self.resolve.return_value = overrides
                with self.assertRaises(RuntimeError):
                    hepta_ci_v8.configure_v8(ROOT, self.output)
                self.assertEqual(self.output.read_text(), "EXISTING=preserved\n")

    def test_compiler_failure_is_not_replaced_with_a_guessed_host(self) -> None:
        self.host_mock.side_effect = subprocess.CalledProcessError(1, ["rustc", "-vV"])
        with self.assertRaises(subprocess.CalledProcessError):
            hepta_ci_v8.configure_v8(ROOT, self.output)
        self.resolve.assert_not_called()
        self.assertEqual(self.output.read_text(), "EXISTING=preserved\n")


if __name__ == "__main__":
    unittest.main()
