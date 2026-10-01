"""Exercise compiler fixtures and lock pinning without launching Cargo."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hepta_ui_native_compile_negative as negative


def with_fixture(seed, name):
    return (
        seed
        + f"""\n[[package]]
name = "ui-native-negative-{name.replace("_", "-")}"
version = "0.0.0"
dependencies = ["hepta-native"]
""".encode()
    )


class CompileNegativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.seed = (negative.ROOT / negative.APP_LOCK).read_bytes()

    def compiler(
        self,
        failure=None,
        normalize_failure=None,
        normalized_lock=None,
        compiler_lock=None,
        compiler_returncode=1,
        host_failure=None,
        host_output=b"rustc 1.95.0\nhost: x86_64-unknown-linux-gnu\n",
    ):
        def execute(arguments, **kwargs):
            if arguments[0] == "rustc":
                self.assertEqual(arguments, ["rustc", "+1.95.0", "-vV"])
                self.assertEqual(kwargs["cwd"], negative.ROOT)
                return subprocess.CompletedProcess(
                    arguments,
                    1 if host_failure is not None else 0,
                    host_output,
                    host_failure or b"",
                )
            manifest = Path(arguments[-1])
            lock = manifest.with_name("Cargo.lock")
            name = manifest.parent.name.split("hepta-", 1)[1].rsplit("-", 1)[0]
            if "metadata" in arguments:
                self.assertEqual(lock.read_bytes(), self.seed)
                expected_host = (
                    host_output.split(b"host: ", 1)[1].splitlines()[0].decode()
                )
                self.assertEqual(
                    arguments,
                    [
                        "cargo",
                        "+1.95.0",
                        "metadata",
                        "--offline",
                        "--format-version",
                        "1",
                        "--filter-platform",
                        expected_host,
                        "--manifest-path",
                        str(manifest),
                    ],
                )
                self.assertEqual(kwargs["cwd"], negative.ROOT)
                if normalize_failure:
                    return subprocess.CompletedProcess(
                        arguments, 1, b"", normalize_failure
                    )
                lock.write_bytes(
                    normalized_lock
                    if normalized_lock is not None
                    else with_fixture(self.seed, name)
                )
                return subprocess.CompletedProcess(arguments, 0, b"{}", b"")
            self.assertEqual(
                arguments,
                [
                    "cargo",
                    "+1.95.0",
                    "check",
                    "--offline",
                    "--locked",
                    "--quiet",
                    "--manifest-path",
                    str(manifest),
                ],
            )
            self.assertEqual(lock.read_bytes(), with_fixture(self.seed, name))
            self.assertEqual(
                kwargs["env"]["CARGO_TARGET_DIR"], str(self.base / "shared-target")
            )
            if compiler_lock is not None:
                lock.write_bytes(compiler_lock)
            diagnostic = (
                f"error[E0603]: module `{name}` is private".encode()
                if failure is None
                else failure
            )
            return subprocess.CompletedProcess(
                arguments, compiler_returncode, b"", diagnostic
            )

        return execute

    def run_case(self, **arguments):
        with patch.dict(
            "os.environ", {"CARGO_TARGET_DIR": str(self.base / "shared-target")}
        ):
            with patch.object(
                negative.subprocess, "run", side_effect=self.compiler(**arguments)
            ) as cargo:
                result = negative.run_case(
                    "journal_storage",
                    negative.CASES["journal_storage"],
                    self.base,
                    self.seed,
                )
                return result, cargo

    def test_exact_current_application_lock_seeds_fixture_then_locked_compiler_check(
        self,
    ):
        result, cargo = self.run_case()
        self.assertEqual(cargo.call_count, 3)
        self.assertEqual(
            result,
            {
                "module": "journal_storage",
                "exitCode": 1,
                "diagnosticSha256": negative.sha256(
                    b"error[E0603]: module `journal_storage` is private"
                ),
                "privacyDiagnosticObserved": True,
                "seedCargoLockSha256": negative.sha256(self.seed),
                "fixtureCargoLockSha256": negative.sha256(
                    with_fixture(self.seed, "journal_storage")
                ),
                "dependencyResolutionPinned": True,
                "lockedCompilerCheck": True,
            },
        )

    def test_host_discovery_failure_reports_error_and_stops_before_normalization(self):
        with patch.object(
            negative.subprocess,
            "run",
            side_effect=self.compiler(host_failure=b"error: toolchain unavailable"),
        ) as cargo:
            with self.assertRaisesRegex(
                RuntimeError,
                "(?s)compiler host discovery failed.*\\n.*toolchain unavailable",
            ):
                negative.run_case(
                    "journal_storage",
                    negative.CASES["journal_storage"],
                    self.base,
                    self.seed,
                )
        self.assertEqual(cargo.call_count, 1)

    def test_metadata_filter_uses_discovered_host(self):
        _, cargo = self.run_case(
            host_output=b"rustc 1.95.0\nhost: aarch64-apple-darwin\n"
        )
        self.assertIn("aarch64-apple-darwin", cargo.call_args_list[1].args[0])

    def test_host_discovery_rejects_missing_ambiguous_or_invalid_host(self):
        for output in (
            b"rustc 1.95.0\n",
            b"host: x86_64-unknown-linux-gnu\nhost: aarch64-apple-darwin\n",
            b"host: x86_64\n",
            b"host: x86_64-unknown-linux-gnu --offline\n",
        ):
            with self.subTest(output=output):
                with patch.object(
                    negative.subprocess,
                    "run",
                    side_effect=self.compiler(host_output=output),
                ) as cargo:
                    with self.assertRaisesRegex(
                        RuntimeError, "invalid or ambiguous host"
                    ):
                        negative.run_case(
                            "journal_storage",
                            negative.CASES["journal_storage"],
                            self.base,
                            self.seed,
                        )
                self.assertEqual(cargo.call_count, 1)

    def test_normalization_that_does_not_add_fixture_stops_before_compiler(self):
        with patch.object(
            negative.subprocess,
            "run",
            side_effect=self.compiler(normalized_lock=self.seed),
        ) as cargo:
            with self.assertRaisesRegex(
                RuntimeError, "normalized lock lacks the external fixture"
            ):
                negative.run_case(
                    "journal_storage",
                    negative.CASES["journal_storage"],
                    self.base,
                    self.seed,
                )
        self.assertEqual(cargo.call_count, 2)

    def test_normalization_that_floats_package_stops_before_compiler(self):
        changed = (
            with_fixture(self.seed, "journal_storage")
            + b"""\n[[package]]
name = "uncached-substitution"
version = "1.0.0"
"""
        )
        with patch.object(
            negative.subprocess,
            "run",
            side_effect=self.compiler(normalized_lock=changed),
        ) as cargo:
            with self.assertRaisesRegex(RuntimeError, "floated beyond application"):
                negative.run_case(
                    "journal_storage",
                    negative.CASES["journal_storage"],
                    self.base,
                    self.seed,
                )
        self.assertEqual(cargo.call_count, 2)

    def test_locked_compiler_check_cannot_mutate_normalized_lock(self):
        with self.assertRaisesRegex(
            RuntimeError, "locked compiler check changed the fixture lock"
        ):
            self.run_case(compiler_lock=self.seed)

    def test_successful_compilation_does_not_pass_even_with_privacy_text(self):
        with self.assertRaisesRegex(
            RuntimeError, "private module journal_storage unexpectedly compiled"
        ):
            self.run_case(compiler_returncode=0)

    def test_main_reads_lock_from_current_source_and_records_its_digest(self):
        app = self.base / "apps/hepta-native"
        app.mkdir(parents=True)
        seed = b'version = 4\n[[package]]\nname = "hepta-native"\nversion = "9.8.7"\n'
        (app / "Cargo.lock").write_bytes(seed)
        output = io.StringIO()
        with (
            patch.object(negative, "ROOT", self.base),
            patch.object(
                negative,
                "git",
                side_effect=lambda *args: "a" * 40 if args[0] == "rev-parse" else "",
            ),
        ):
            with patch.object(
                negative, "run_case", return_value={"privacyDiagnosticObserved": True}
            ) as fixture:
                with (
                    patch.dict("os.environ", {"NATIVE_EXPECTED_HEAD": "a" * 40}),
                    contextlib.redirect_stdout(output),
                ):
                    self.assertEqual(negative.main(), 0)
        self.assertEqual(fixture.call_count, 3)
        for invocation in fixture.call_args_list:
            self.assertEqual(invocation.args[-1], seed)
        self.assertEqual(
            json.loads(output.getvalue())["applicationCargoLockSha256"],
            negative.sha256(seed),
        )

    def test_nonprivacy_failure_includes_original_compiler_diagnostic(self):
        with self.assertRaisesRegex(
            RuntimeError, "reason other than privacy.*\\nerror: uncached js-sys 0.3.85"
        ):
            self.run_case(failure=b"error: uncached js-sys 0.3.85")

    def test_another_private_module_does_not_prove_requested_module_is_private(self):
        with self.assertRaisesRegex(
            RuntimeError, "missing private-module diagnostic for journal_storage"
        ):
            self.run_case(failure=b"error[E0603]: module `retirement` is private")

    def test_module_text_without_privacy_error_code_does_not_pass(self):
        with self.assertRaisesRegex(RuntimeError, "reason other than privacy"):
            self.run_case(failure=b"error: module `journal_storage` is private")

    def test_empty_compiler_diagnostic_reports_missing_output(self):
        with self.assertRaisesRegex(
            RuntimeError, "compiler produced no diagnostic output"
        ):
            self.run_case(failure=b"")

    def test_normalization_failure_reports_resolver_error_and_stops_compiler(self):
        with patch.object(
            negative.subprocess,
            "run",
            side_effect=self.compiler(
                normalize_failure=b"error: wgpu needs js-sys ^0.3.104"
            ),
        ) as cargo:
            with self.assertRaisesRegex(
                RuntimeError, "normalization failed.*\\nerror: wgpu needs js-sys"
            ):
                negative.run_case(
                    "journal_storage",
                    negative.CASES["journal_storage"],
                    self.base,
                    self.seed,
                )
        self.assertEqual(cargo.call_count, 2)

    def test_normalization_failure_diagnostic_is_bounded(self):
        with self.assertRaises(RuntimeError) as failure:
            self.run_case(
                normalize_failure=b"resolver begin" + b"x" * 20000 + b"resolver end"
            )
        message = str(failure.exception)
        self.assertLess(len(message), 16200)
        self.assertIn("resolver begin", message)
        self.assertIn("diagnostic output truncated", message)
        self.assertTrue(message.endswith("resolver end"))

    def test_diagnostic_output_is_bounded_but_retains_beginning_and_end(self):
        result = subprocess.CompletedProcess([], 1, b"begin" + b"x" * 20000, b"end")
        output = negative.diagnostics(result)
        self.assertLess(len(output), 16100)
        self.assertTrue(output.startswith("begin"))
        self.assertTrue(output.endswith("end"))


class FixtureLockTests(unittest.TestCase):
    SEED = b"""version = 4
[[package]]
name = "hepta-native"
version = "0.1.0"
dependencies = ["getrandom 0.4.3", "tempfile"]
[[package]]
name = "getrandom"
version = "0.2.0"
[[package]]
name = "getrandom"
version = "0.4.3"
checksum = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
[[package]]
name = "tempfile"
version = "3.23.0"
dependencies = ["getrandom 0.2.0"]
"""
    PRUNED = b"""version = 4
[[package]]
name = "hepta-native"
version = "0.1.0"
dependencies = ["getrandom"]
[[package]]
name = "getrandom"
version = "0.4.3"
checksum = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
"""

    def verify(self, value):
        negative.verify_fixture_lock(
            self.SEED, with_fixture(value, "journal_storage"), "journal_storage"
        )

    def test_reachable_packages_stay_pinned_when_cargo_prunes_dev_only_entries(self):
        self.verify(self.PRUNED)

    def test_floating_version_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "floated beyond application"):
            self.verify(self.PRUNED.replace(b"0.4.3", b"0.4.4"))

    def test_rehashed_dependency_checksum_substitution_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "metadata or checksum"):
            self.verify(self.PRUNED.replace(b"a" * 64, b"b" * 64))

    def test_changed_dependency_edge_rejected(self):
        modified = self.SEED.replace(
            b'"getrandom 0.4.3", "tempfile"', b'"getrandom 0.2.0", "tempfile"'
        )
        with self.assertRaisesRegex(RuntimeError, "changed locked dependency edges"):
            self.verify(modified)


if __name__ == "__main__":
    unittest.main()
