"""Synthetic guard controls; these never compile or enter the Root phase."""

import copy
import hashlib
from pathlib import Path
import tempfile
import time
import unittest
import sys
import os
import subprocess
from unittest import mock

from scripts import hepta_ci_paired_root as gate


@unittest.skipUnless(
    sys.platform == "linux", "the isolated Root gate is explicitly Linux-only"
)
class PairedRootGateTests(unittest.TestCase):
    def test_identity_requires_the_exact_hosted_source_lane(self):
        environment = {
            "GITHUB_ACTIONS": "true",
            "RUNNER_ENVIRONMENT": "github-hosted",
            "RUNNER_OS": "Linux",
            "HEPTA_CI_LANE": "source-head",
            "SOURCE_SHA": "1" * 40,
            "TESTED_SHA": "1" * 40,
            "GITHUB_RUN_ID": "12345",
            "GITHUB_RUN_ATTEMPT": "1",
        }
        self.assertEqual(
            gate.context(environment),
            {"source": "1" * 40, "run_id": "12345", "attempt": "1"},
        )
        for key, changed in (
            ("RUNNER_ENVIRONMENT", "self-hosted"),
            ("TESTED_SHA", "2" * 40),
            ("HEPTA_CI_LANE", "base-merge"),
            ("GITHUB_RUN_ATTEMPT", "../old"),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.context({**environment, key: changed})

    def test_metadata_rejects_a_foreign_package_kind_or_replaced_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            manifest = root / "codex-rs/hepta-agentd/Cargo.toml"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("synthetic metadata only")
            target = root / "target"
            target.mkdir()
            binary = target / "libtest"
            binary.write_bytes(b"synthetic binary identity, never executed")
            cargo = {
                "target_directory": str(target),
                "packages": [
                    {
                        "name": "codex-hepta-agentd",
                        "id": "original-id",
                        "manifest_path": str(manifest),
                    }
                ],
            }
            metadata = {
                "rust-binaries": {
                    "codex-hepta-agentd": {
                        "binary-id": "codex-hepta-agentd",
                        "binary-name": "codex_hepta_agentd",
                        "package-id": "original-id",
                        "kind": "lib",
                        "binary-path": str(binary),
                    }
                }
            }
            self.assertEqual(gate.binary_from_metadata(metadata, cargo, root), binary)
            for field, value in (
                ("package-id", "foreign"),
                ("kind", "bin"),
                ("binary-path", str(manifest)),
            ):
                changed = copy.deepcopy(metadata)
                changed["rust-binaries"]["codex-hepta-agentd"][field] = value
                with self.subTest(field=field), self.assertRaises(ValueError):
                    gate.binary_from_metadata(changed, cargo, root)
            original = target / "original"
            binary.rename(original)
            binary.symlink_to(original)
            with self.assertRaises(ValueError):
                gate.binary_from_metadata(metadata, cargo, root)

    def test_original_output_requires_one_exact_nonignored_success(self):
        output = (
            f"running 1 test\ntest {gate.TEST} ... ok\n\n"
            "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 999 filtered out; finished in 0.01s\n"
        ).encode()
        gate.one_test_passed(output)
        for raw in (
            output.replace(b"1 passed", b"0 passed"),
            output.replace(b"0 ignored", b"1 ignored"),
            output.replace(b"running 1 test", b"running 2 tests"),
            output.replace(gate.TEST.encode(), b"some_other_test"),
            output + output,
            output.replace(b"... ok", b"... ignored"),
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                gate.one_test_passed(raw)

    def test_copy_uses_the_exact_bytes_and_shared_deadline_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            payload = b"synthetic binary bytes, never executed"
            source.write_bytes(payload)
            expected = {
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            target = root / "original"
            gate.copy_binary(
                source, target, expected, time.monotonic_ns() + 20_000_000_000
            )
            self.assertEqual(target.read_bytes(), payload)
            source.write_bytes(payload[:-1] + b"!")
            with self.assertRaises(ValueError):
                gate.copy_binary(
                    source,
                    root / "changed",
                    expected,
                    time.monotonic_ns() + 20_000_000_000,
                )
            with self.assertRaises(ValueError):
                gate.copy_binary(
                    source, root / "expired", expected, time.monotonic_ns() - 1
                )

    def test_nonroot_collector_refuses_a_caller_written_root_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = root / "ROOT_RESULT.json"
            record.write_text('{"status":"passed"}')
            record.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "original evidence owner required"):
                gate.collect(root)

    def test_bounded_reader_keeps_the_opened_original_when_path_is_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "original"
            path.write_bytes(b"original recorded bytes")
            path.chmod(0o600)
            original_open = os.open

            def replace_after_open(name, flags, *args, **kwargs):
                descriptor = original_open(name, flags, *args, **kwargs)
                path.rename(root / "retained")
                path.write_bytes(b"caller replacement")
                return descriptor

            with mock.patch.object(gate.os, "open", side_effect=replace_after_open):
                raw = gate.read_bounded(path, 1024, owner_uid=os.getuid(), mode=0o600)
            self.assertEqual(raw, b"original recorded bytes")
            self.assertEqual(path.read_bytes(), b"caller replacement")

    def test_publication_uses_held_directory_and_fchmods_only_created_inode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle"
            bundle.mkdir()
            descriptor = os.open(bundle, os.O_RDONLY | os.O_DIRECTORY)
            retained = root / "retained"
            bundle.rename(retained)
            bundle.mkdir()
            foreign = root / "foreign"
            foreign.write_bytes(b"unchanged foreign file")
            foreign.chmod(0o600)
            (bundle / "receipt").symlink_to(foreign)
            try:
                gate.write_raw(
                    "receipt", b"original receipt", directory_fd=descriptor, mode=0o644
                )
                self.assertEqual(
                    (retained / "receipt").read_bytes(), b"original receipt"
                )
                self.assertEqual(foreign.stat().st_mode & 0o777, 0o600)
                self.assertEqual(foreign.read_bytes(), b"unchanged foreign file")
                (retained / "blocked").symlink_to(foreign)
                with self.assertRaises(OSError):
                    gate.write_raw(
                        "blocked",
                        b"must not follow",
                        directory_fd=descriptor,
                        mode=0o644,
                    )
            finally:
                os.close(descriptor)

    def test_fifo_without_a_writer_is_rejected_before_any_blocking_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fifo = root / "fifo"
            os.mkfifo(fifo)
            program = """
import pathlib, sys, time
sys.path.insert(0, sys.argv[1])
import hepta_ci_paired_root as gate
fifo = pathlib.Path(sys.argv[2])
checks = (
    lambda: gate.read_bounded(fifo, 1024),
    lambda: gate.sha256(fifo, 1024),
    lambda: gate.copy_binary(fifo, fifo.parent / 'copy', {'bytes': 1, 'sha256': '0' * 64}, time.monotonic_ns() + 20_000_000_000),
)
for check in checks:
    try:
        check()
    except ValueError:
        continue
    raise AssertionError('FIFO was not rejected')
"""
            process = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    program,
                    str(Path(gate.__file__).parent),
                    str(fifo),
                ],
                capture_output=True,
                timeout=2,
                check=False,
            )
            self.assertEqual(
                (process.returncode, process.stdout, process.stderr), (0, b"", b"")
            )


if __name__ == "__main__":
    unittest.main()
