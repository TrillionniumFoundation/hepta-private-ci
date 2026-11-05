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
import test_hepta_windows_boundary_receipts as original


class PreparedOwnerReceiptTests(unittest.TestCase):
    def registry(self):
        return {"rust-suites": {"codex-windows-sandbox": {
            "binary-id": "codex-windows-sandbox", "package-name": "codex-windows-sandbox",
            "binary-name": "codex_windows_sandbox", "kind": "lib", "status": "listed",
            "binary-path": "C:/synthetic-target/codex_windows_sandbox.exe",
            "testcases": {name: {"ignored": False, "filter-match": {"status": "matches"}} for name in owner.CASES},
        }}}

    def fixture(self):
        raw = json.dumps(self.registry()).encode()
        prepared = {"registry_sha256": hashlib.sha256(raw).hexdigest(), "selected": owner.selected_suite(json.loads(raw))}
        source = {"scope": "synthetic structure only", "tested_sha": "a" * 40}
        pe = {"format": "PE32+", "machine": 0x8664, "sha256": "b" * 64, "st_ino": 42}
        return [source, copy.deepcopy(source), copy.deepcopy(source), prepared, raw, pe, copy.deepcopy(pe), original.log(owner.CASES).encode(), [0, 0]]

    def test_exact_source_roster_and_separate_workflow_keep_original_twenty(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "codex-rs/windows-sandbox-rs/src/prepared_process_context_tests.rs").read_text()
        names = re.findall(r"^#\[test\]\nfn ([a-z0-9_]+)\(", source, re.MULTILINE)
        self.assertEqual(tuple("process::prepared_context::tests::" + name for name in names), owner.CASES)
        workflow = original.WORKFLOW.read_text()
        self.assertEqual(workflow.count("just test --locked -p codex-windows-sandbox --lib -E '" + owner.SELECTOR + "' --test-threads 1 --no-capture"), 1)
        self.assertIn("runner: [windows-latest, windows-11-arm]", workflow)
        self.assertIn("hepta-windows-delete-boundary-${{ matrix.runner }}", workflow)
        self.assertIn("hepta-windows-prepared-owner-${{ matrix.runner }}", workflow)
        tree = ast.parse(original.reader())
        assignments = {target.id: node for node in tree.body if isinstance(node, ast.Assign) for target in node.targets if isinstance(target, ast.Name)}
        namespace = {}
        exec(compile(ast.Module(body=[assignments[key] for key in ("probes", "store_selectors", "required")], type_ignores=[]), "original-twenty", "exec"), namespace)
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
                suite["testcases"]["unexpected"] = copy.deepcopy(suite["testcases"][owner.CASES[0]])
            elif change == "ignored":
                suite["testcases"][owner.CASES[0]]["ignored"] = True
            elif change == "filtered":
                suite["testcases"][owner.CASES[0]]["filter-match"]["status"] = "mismatch"
            elif change == "binary":
                suite["binary-name"] = "wrong"
            else:
                registry["rust-suites"]["wrong"] = copy.deepcopy(suite)
            with self.subTest(change=change), self.assertRaises(ValueError):
                owner.selected_suite(registry)

    def test_log_missing_duplicate_failed_retried_and_bad_codes_are_refused(self):
        raw = original.log(owner.CASES)
        missing = original.log(owner.CASES[:-1], passed=3).replace("2 tests run:", "3 tests run:")
        invalid = [missing, raw + raw, raw + "test " + owner.CASES[0] + " ... ok\n", raw.replace(owner.CASES[0], "wrong"), raw + "FAIL [0.1s] old attempt\n", raw + "TMT [60.00s] timed out attempt\n", raw + "RETRY test\n", raw + "FLAKY 2/2 retry\n", raw.replace("3 passed", "3 passed (1 flaky)"), original.log(owner.CASES, failed=1), original.log(())]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                owner.execution_receipt(value.encode(), [0, 0])
        for codes in ([1, 0], [0, 1], [False, 0], [0], [0, 0, 0]):
            with self.subTest(codes=codes), self.assertRaises(ValueError):
                owner.execution_receipt(raw.encode(), codes)

    def test_ansi_indented_summary_preserves_exact_three(self):
        raw = original.log(owner.CASES).replace("Summary", "\x1b[32;1m     Summary\x1b[0m")
        self.assertEqual(owner.execution_receipt(raw.encode(), [0, 0])["observed_passed_test_names"], list(owner.CASES))

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

    def test_always_finish_retains_failed_test_exit_without_touching_original_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "windows-prepared-owner"
            directory.mkdir()
            original_directory = root / "windows-delete-boundary"
            original_directory.mkdir()
            original_bytes = b'{"status":"failed","scope":"synthetic original result"}\n'
            (original_directory / "result.json").write_bytes(original_bytes)
            for phase in ("before", "prepare", "run"):
                owner.save(directory, phase + "-phase.json", {"phase": phase, "status": "failed" if phase == "run" else "recorded"})
            owner.save(directory, "run-codes.json", [7, 0])
            with mock.patch.object(owner.sys, "argv", ["receipt", "finish", str(directory)]), mock.patch.dict(owner.os.environ, {"RUNNER_TEMP": temporary}), mock.patch.object(owner, "source_snapshot") as snapshot, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(owner.main(), 1)
                snapshot.assert_not_called()
            receipt = owner.load(directory, "receipt.json")
            self.assertEqual((receipt["status"], receipt["actual_test_exit_codes"]), ("failed", [7, 0]))
            self.assertEqual((original_directory / "result.json").read_bytes(), original_bytes)

    def test_pe32_plus_parser_checks_native_headers_and_both_machine_values(self):
        for machine in owner.MACHINES.values():
            raw = bytearray(128)
            raw[:2] = b"MZ"
            struct.pack_into("<I", raw, 60, 64)
            raw[64:68] = b"PE\0\0"
            struct.pack_into("<H", raw, 68, machine)
            raw[88:90] = b"\x0b\x02"
            self.assertEqual(owner.pe_machine(io.BytesIO(raw), len(raw)), machine)
            for offset, value in ((0, b"\x7fELF"), (60, b"\xff\xff\xff\xff"), (64, b"bad!"), (88, b"\x0b\x01")):
                invalid = raw.copy()
                invalid[offset:offset + len(value)] = value
                with self.subTest(machine=machine, offset=offset), self.assertRaises(ValueError):
                    owner.pe_machine(io.BytesIO(invalid), len(invalid))


if __name__ == "__main__":
    unittest.main()
