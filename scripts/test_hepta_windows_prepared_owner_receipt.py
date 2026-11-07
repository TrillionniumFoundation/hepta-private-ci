"""Synthetic structure controls only: no Rust, Windows API or native qualification."""

import ast
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import tempfile
import unittest
from unittest import mock

import hepta_windows_prepared_owner_receipt as owner
import hepta_windows_pe_identity as native_pe
import test_hepta_windows_boundary_receipts as original


class PreparedOwnerReceiptTests(unittest.TestCase):
    def registry(self):
        return {
            "rust-suites": {
                "codex-windows-sandbox": {
                    "binary-id": "codex-windows-sandbox",
                    "package-name": "codex-windows-sandbox",
                    "binary-name": "codex_windows_sandbox",
                    "kind": "lib",
                    "status": "listed",
                    "binary-path": "C:/synthetic-target/codex_windows_sandbox.exe",
                    "testcases": {
                        name: {"ignored": False, "filter-match": {"status": "matches"}}
                        for name in owner.CASES
                    },
                }
            }
        }

    def fixture(self):
        raw = json.dumps(self.registry()).encode()
        prepared = {
            "registry_sha256": hashlib.sha256(raw).hexdigest(),
            "selected": owner.selected_suite(json.loads(raw)),
        }
        source = {"scope": "synthetic structure only", "tested_sha": "a" * 40}
        pe = {"format": "PE32+", "machine": 0x8664, "sha256": "b" * 64, "st_ino": 42}
        return [
            source,
            copy.deepcopy(source),
            copy.deepcopy(source),
            prepared,
            raw,
            pe,
            copy.deepcopy(pe),
            original.log(owner.CASES).encode(),
            [0, 0],
        ]

    def test_exact_source_roster_and_separate_workflow_keep_original_twenty(self):
        root = Path(__file__).resolve().parents[1]
        source = (
            root / "codex-rs/windows-sandbox-rs/src/prepared_process_context_tests.rs"
        ).read_text()
        names = re.findall(r"^#\[test\]\nfn ([a-z0-9_]+)\(", source, re.MULTILINE)
        self.assertEqual(
            tuple("process::prepared_context::tests::" + name for name in names),
            owner.CASES,
        )
        workflow = original.WORKFLOW.read_text()
        self.assertEqual(
            workflow.count(
                "just test --locked -p codex-windows-sandbox --lib -E '"
                + owner.SELECTOR
                + "' --test-threads 1 --no-capture"
            ),
            1,
        )
        self.assertIn("runner: [windows-latest, windows-11-arm]", workflow)
        self.assertIn("hepta-windows-delete-boundary-${{ matrix.runner }}", workflow)
        self.assertIn("hepta-windows-prepared-owner-${{ matrix.runner }}", workflow)
        tree = ast.parse(original.reader())
        assignments = {
            target.id: node
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        namespace = {}
        exec(
            compile(
                ast.Module(
                    body=[
                        assignments[key]
                        for key in ("probes", "store_selectors", "required")
                    ],
                    type_ignores=[],
                ),
                "original-twenty",
                "exec",
            ),
            namespace,
        )
        self.assertEqual(len(namespace["required"]), 20)
        self.assertIn("broad-identity-delete", namespace["required"])
        self.assertIn("legacy-delete-boundary", namespace["required"])
        self.assertNotIn("prepared-owner", namespace["required"])

    def test_complete_structure_is_accepted_without_native_pass_claim(self):
        result = owner.reconcile(*self.fixture())
        self.assertEqual(result["observed_passed_tests"], 3)
        self.assertNotIn("status", result)
        self.assertNotIn("production_sandbox_admitted", result)

    def test_registry_missing_extra_ignored_and_wrong_binary_are_refused(self):
        for change in ("missing", "extra", "ignored", "filtered", "binary", "second"):
            registry = self.registry()
            suite = registry["rust-suites"]["codex-windows-sandbox"]
            if change == "missing":
                del suite["testcases"][owner.CASES[0]]
            elif change == "extra":
                suite["testcases"]["unexpected"] = copy.deepcopy(
                    suite["testcases"][owner.CASES[0]]
                )
            elif change == "ignored":
                suite["testcases"][owner.CASES[0]]["ignored"] = True
            elif change == "filtered":
                suite["testcases"][owner.CASES[0]]["filter-match"]["status"] = (
                    "mismatch"
                )
            elif change == "binary":
                suite["binary-name"] = "wrong"
            else:
                registry["rust-suites"]["wrong"] = copy.deepcopy(suite)
            with self.subTest(change=change), self.assertRaises(ValueError):
                owner.selected_suite(registry)

    def test_log_missing_duplicate_failed_retried_and_bad_codes_are_refused(self):
        raw = original.log(owner.CASES)
        missing = original.log(owner.CASES[:-1], passed=3).replace(
            "2 tests run:", "3 tests run:"
        )
        invalid = [
            missing,
            raw + raw,
            raw + "test " + owner.CASES[0] + " ... ok\n",
            raw.replace(owner.CASES[0], "wrong"),
            raw + "FAIL [0.1s] old attempt\n",
            raw + "TMT [60.00s] timed out attempt\n",
            raw + "RETRY test\n",
            raw + "FLAKY 2/2 retry\n",
            raw.replace("3 passed", "3 passed (1 flaky)"),
            original.log(owner.CASES, failed=1),
            original.log(()),
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                owner.execution_receipt(value.encode(), [0, 0])
        for codes in ([1, 0], [0, 1], [False, 0], [0], [0, 0, 0]):
            with self.subTest(codes=codes), self.assertRaises(ValueError):
                owner.execution_receipt(raw.encode(), codes)

    def test_ansi_indented_summary_preserves_exact_three(self):
        raw = original.log(owner.CASES).replace(
            "Summary", "\x1b[32;1m     Summary\x1b[0m"
        )
        self.assertEqual(
            owner.execution_receipt(raw.encode(), [0, 0])["observed_passed_test_names"],
            list(owner.CASES),
        )

    def test_source_registry_and_actual_pe_drift_each_refuse(self):
        for index in (0, 1, 2, 3, 4, 5, 6):
            values = self.fixture()
            if index == 4:
                values[index] += b" "
            elif index == 3:
                values[index]["selected"]["path"] = "C:/wrong.exe"
            elif index in (5, 6):
                values[index]["sha256"] = "c" * 64
            else:
                values[index]["changed"] = True
            with self.subTest(index=index), self.assertRaises(ValueError):
                owner.reconcile(*values)

    def test_always_finish_retains_failed_test_exit_without_touching_original_result(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "windows-prepared-owner"
            directory.mkdir()
            original_directory = root / "windows-delete-boundary"
            original_directory.mkdir()
            original_bytes = (
                b'{"status":"failed","scope":"synthetic original result"}\n'
            )
            (original_directory / "result.json").write_bytes(original_bytes)
            for phase in ("before", "prepare", "run"):
                owner.save(
                    directory,
                    phase + "-phase.json",
                    {
                        "phase": phase,
                        "status": "failed" if phase == "run" else "recorded",
                    },
                )
            owner.save(directory, "run-codes.json", [7, 0])
            with (
                mock.patch.object(
                    owner.sys, "argv", ["receipt", "finish", str(directory)]
                ),
                mock.patch.dict(owner.os.environ, {"RUNNER_TEMP": temporary}),
                mock.patch.object(owner, "source_snapshot") as snapshot,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(owner.main(), 1)
                snapshot.assert_not_called()
            receipt = owner.load(directory, "receipt.json")
            self.assertEqual(
                (receipt["status"], receipt["actual_test_exit_codes"]),
                ("failed", [7, 0]),
            )
            self.assertEqual(
                (original_directory / "result.json").read_bytes(), original_bytes
            )

    def test_pe32_plus_parser_checks_native_headers_and_both_machine_values(self):
        for machine in owner.MACHINES.values():
            raw = bytearray(128)
            raw[:2] = b"MZ"
            struct.pack_into("<I", raw, 60, 64)
            raw[64:68] = b"PE\0\0"
            struct.pack_into("<H", raw, 68, machine)
            raw[88:90] = b"\x0b\x02"
            self.assertEqual(owner.pe_machine(io.BytesIO(raw), len(raw)), machine)
            for offset, value in (
                (0, b"\x7fELF"),
                (60, b"\xff\xff\xff\xff"),
                (64, b"bad!"),
                (88, b"\x0b\x01"),
            ):
                invalid = raw.copy()
                invalid[offset : offset + len(value)] = value
                with (
                    self.subTest(machine=machine, offset=offset),
                    self.assertRaises(ValueError),
                ):
                    owner.pe_machine(io.BytesIO(invalid), len(invalid))


class NativeHandleStructureTests(unittest.TestCase):
    """Synthetic handles exercise reader refusal paths, not Win32 execution."""

    def fixture(self, machine=0x8664):
        raw = bytearray(128)
        raw[:2] = b"MZ"
        struct.pack_into("<I", raw, 60, 64)
        raw[64:68] = b"PE\0\0"
        struct.pack_into("<H", raw, 68, machine)
        raw[88:90] = b"\x0b\x02"
        record = {
            "path": "C:\\target\\deps\\test.exe",
            "volume_serial": 123,
            "file_id_128": "01" * 16,
            "file_type": 1,
            "attributes": 0x20,
            "reparse_tag": 0,
            "size": len(raw),
            "allocation_size": 4096,
            "links": 2,
            "delete_pending": False,
            "directory": False,
            "creation_time_100ns": 10,
            "last_write_time_100ns": 20,
            "change_time_100ns": 30,
        }
        records = [copy.deepcopy(record) for _ in range(4)]

        class Files:
            def __init__(self):
                self.opened = []
                self.observed_streams = []

            def open(self, path):
                stream = io.BytesIO(raw)
                self.opened.append(stream)
                return stream

            def snapshot(self, stream):
                self.observed_streams.append(stream)
                return records[len(self.observed_streams) - 1]

        return raw, records, Files()

    def observe(self, files, target="x86_64-pc-windows-msvc"):
        return native_pe.observe_pe(
            "C:\\target\\deps\\test.exe", target, "C:\\target", files
        )

    def test_same_held_handle_hashes_both_native_machine_shapes_and_reopens_name(self):
        for target, machine in native_pe.MACHINES.items():
            raw, records, files = self.fixture(machine)
            with self.subTest(target=target):
                result = self.observe(files, target)
                self.assertEqual(result["sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(result["file_id_128"], records[0]["file_id_128"])
                self.assertEqual(
                    files.observed_streams,
                    [
                        files.opened[0],
                        files.opened[0],
                        files.opened[1],
                        files.opened[0],
                    ],
                )
                self.assertTrue(all(stream.closed for stream in files.opened))

    def test_file_identity_size_time_attributes_or_links_drift_is_refused(self):
        fields = {
            "volume_serial": 456,
            "file_id_128": "02" * 16,
            "size": 127,
            "allocation_size": 8192,
            "links": 3,
            "attributes": 0x21,
            "creation_time_100ns": 11,
            "last_write_time_100ns": 21,
            "change_time_100ns": 31,
        }
        for index in (1, 2, 3):
            for field, value in fields.items():
                _, records, files = self.fixture()
                records[index][field] = value
                with (
                    self.subTest(index=index, field=field),
                    self.assertRaises(ValueError),
                ):
                    self.observe(files)
                self.assertTrue(all(stream.closed for stream in files.opened))

    def test_missing_identity_reparse_delete_pending_and_nondisk_refuse(self):
        fields = {
            "volume_serial": 0,
            "file_id_128": "00" * 16,
            "file_type": 3,
            "attributes": 0x400,
            "reparse_tag": 0xA000000C,
            "directory": True,
            "delete_pending": True,
            "links": 0,
        }
        for index in (0, 2):
            for field, value in fields.items():
                _, records, files = self.fixture()
                records[index][field] = value
                with (
                    self.subTest(index=index, field=field),
                    self.assertRaises(ValueError),
                ):
                    self.observe(files)

    def test_opened_path_outside_target_and_same_prefix_sibling_refuse(self):
        for path in (
            "C:\\elsewhere\\test.exe",
            "C:\\target-other\\test.exe",
            "C:\\target\\..\\test.exe",
        ):
            _, records, files = self.fixture()
            records[0]["path"] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.observe(files)
        self.assertEqual(
            native_pe.windows_path("\\\\?\\C:\\target\\test.exe"),
            native_pe.windows_path("c:/target/test.exe"),
        )
        self.assertEqual(
            native_pe.windows_path("\\\\?\\UNC\\server\\share\\test.exe"),
            native_pe.windows_path("\\\\server\\share\\test.exe"),
        )

    def test_header_hash_and_identity_use_same_stream_and_refuse_wrong_machine(self):
        raw, _, files = self.fixture(0xAA64)
        with self.assertRaises(ValueError):
            self.observe(files)
        raw, _, files = self.fixture()
        raw[64:68] = b"nope"
        with self.assertRaises(ValueError):
            self.observe(files)

    def test_truncated_or_growing_stream_refuses_without_metadata_change(self):
        for amount in (-1, 1):
            raw, _, files = self.fixture()
            if amount < 0:
                raw.pop()
            else:
                raw.append(0)
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.observe(files)

    def test_windows_structure_layouts_keep_full_file_id_and_native_timestamps(self):
        import ctypes

        self.assertEqual(
            [
                ctypes.sizeof(kind)
                for kind in (
                    native_pe.FileIdInfo,
                    native_pe.FileBasicInfo,
                    native_pe.FileStandardInfo,
                    native_pe.FileAttributeTagInfo,
                )
            ],
            [24, 40, 24, 8],
        )
        self.assertEqual(native_pe.FileIdInfo.identifier.offset, 8)
        self.assertEqual(native_pe.FileBasicInfo.changed.offset, 24)

    def test_unavailable_backend_or_native_identity_query_refuses_without_fallback(
        self,
    ):
        with (
            mock.patch.object(native_pe.os, "name", "posix"),
            self.assertRaises(ValueError),
        ):
            native_pe.Win32Files()
        files = native_pe.Win32Files.__new__(native_pe.Win32Files)
        files.api = mock.Mock()
        files.msvcrt = mock.Mock()
        files.api.GetFileInformationByHandleEx.side_effect = OSError(
            "synthetic identity unavailable"
        )
        with self.assertRaises(OSError):
            files.snapshot(mock.Mock())
        files.api.GetFinalPathNameByHandleW.assert_not_called()


if __name__ == "__main__":
    unittest.main()
