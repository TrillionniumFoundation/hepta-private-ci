"""Synthetic evidence controls, not Windows or product qualification."""

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

import hepta_windows_process_root_pins_receipt as pins
import hepta_windows_prepared_owner_receipt as owner
import test_hepta_windows_boundary_receipts as original


class ProcessRootPinReceiptTests(unittest.TestCase):
    def registry(self):
        return {
            "rust-suites": {
                "codex-windows-sandbox": {
                    "binary-id": "codex-windows-sandbox",
                    "package-name": "codex-windows-sandbox",
                    "binary-name": "codex_windows_sandbox",
                    "kind": "lib",
                    "status": "listed",
                    "binary-path": "C:/synthetic-target/test.exe",
                    "testcases": {
                        name: {"ignored": False, "filter-match": {"status": "matches"}}
                        for name in pins.CASES
                    },
                }
            }
        }

    def fixture(self):
        raw = json.dumps(self.registry()).encode()
        prepared = {
            "registry_sha256": hashlib.sha256(raw).hexdigest(),
            "selected": pins.selected_suite(json.loads(raw)),
        }
        source = {"scope": "synthetic structure only", "tested_sha": "a" * 40}
        pe = {
            "format": "PE32+",
            "machine": 0x8664,
            "sha256": "b" * 64,
            "file_id_128": "01" * 16,
        }
        return [
            source,
            copy.deepcopy(source),
            copy.deepcopy(source),
            prepared,
            raw,
            pe,
            copy.deepcopy(pe),
            original.log(pins.CASES).encode(),
            [0, 0],
        ]

    def test_source_rosters_are_disjoint_and_original_three_command_remains_exact(self):
        root = Path(__file__).resolve().parents[1]
        directory = root / "codex-rs/windows-sandbox-rs/src"
        source = (directory / "prepared_process_root_pins_tests.rs").read_text()
        names = re.findall(r"^#\[test\]\nfn ([a-z0-9_]+)\(", source, re.MULTILINE)
        self.assertEqual(
            tuple(
                "process::prepared_context::root_pins_tests::" + name for name in names
            ),
            pins.CASES,
        )
        parent = (directory / "prepared_process_context.rs").read_text()
        self.assertIn(
            '#[path = "prepared_process_root_pins_tests.rs"]\nmod root_pins_tests;',
            parent,
        )
        old_source = (directory / "prepared_process_context_tests.rs").read_text()
        self.assertNotIn("root_pins", old_source)
        old_names = re.findall(
            r"^#\[test\]\nfn ([a-z0-9_]+)\(", old_source, re.MULTILINE
        )
        self.assertEqual(
            tuple("process::prepared_context::tests::" + name for name in old_names),
            owner.CASES,
        )
        self.assertFalse(set(owner.CASES) & set(pins.CASES))
        workflow = original.WORKFLOW.read_text()
        for selector in (owner.SELECTOR, pins.SELECTOR):
            self.assertEqual(
                workflow.count(
                    "just test --locked -p codex-windows-sandbox --lib -E '"
                    + selector
                    + "' --test-threads 1 --no-capture"
                ),
                1,
            )
        self.assertIn("runner: [windows-latest, windows-11-arm]", workflow)

    def test_complete_structure_does_not_claim_native_or_production_qualification(self):
        result = pins.reconcile(*self.fixture())
        self.assertEqual(result["observed_passed_tests"], 2)
        self.assertNotIn("status", result)
        self.assertNotIn("production_sandbox_admitted", result)

    def test_missing_extra_ignored_filtered_or_old_three_registry_refuses(self):
        for change in ("missing", "extra", "ignored", "filtered", "old", "binary"):
            registry = self.registry()
            suite = registry["rust-suites"]["codex-windows-sandbox"]
            if change == "missing":
                del suite["testcases"][pins.CASES[0]]
            elif change == "extra":
                suite["testcases"]["unexpected"] = copy.deepcopy(
                    suite["testcases"][pins.CASES[0]]
                )
            elif change == "ignored":
                suite["testcases"][pins.CASES[0]]["ignored"] = True
            elif change == "filtered":
                suite["testcases"][pins.CASES[0]]["filter-match"]["status"] = "mismatch"
            elif change == "old":
                suite["testcases"] = {
                    name: {"ignored": False, "filter-match": {"status": "matches"}}
                    for name in owner.CASES
                }
            else:
                suite["binary-name"] = "wrong"
            with self.subTest(change=change), self.assertRaises(ValueError):
                pins.selected_suite(registry)

    def test_logs_missing_duplicate_failed_retried_or_wrong_scope_refuse(self):
        raw = original.log(pins.CASES)
        invalid = [
            original.log(pins.CASES[:-1], passed=2).replace(
                "1 tests run:", "2 tests run:"
            ),
            original.log(owner.CASES),
            raw + raw,
            raw + "test " + pins.CASES[0] + " ... ok\n",
            raw.replace(pins.CASES[0], "wrong"),
            raw + "FAIL [0.1s] prior attempt\n",
            raw + "TMT [60.0s] timed out attempt\n",
            raw + "TRY 1 FAIL [0.1s] old attempt\n",
            raw + "FLAKY 2/2 retry\n",
            raw.replace("2 passed", "2 passed (1 flaky)"),
            original.log(pins.CASES, failed=1),
            original.log(()),
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                pins.execution_receipt(value.encode(), [0, 0])
        for codes in ([1, 0], [0, 1], [False, 0], [0], [0, 0, 0]):
            with self.subTest(codes=codes), self.assertRaises(ValueError):
                pins.execution_receipt(raw.encode(), codes)

    def test_ansi_summary_preserves_the_exact_two_names(self):
        raw = original.log(pins.CASES).replace("Summary", "\x1b[32m     Summary\x1b[0m")
        self.assertEqual(
            pins.execution_receipt(raw.encode(), [0, 0])["observed_passed_test_names"],
            list(pins.CASES),
        )

    def test_source_registry_and_actual_pe_drift_refuse_independently(self):
        for index in range(7):
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
                pins.reconcile(*values)

    def test_finish_retains_failure_without_overwriting_original_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "windows-process-root-pins"
            directory.mkdir()
            original_directory = root / "windows-delete-boundary"
            original_directory.mkdir()
            prior_result = b'{"status":"failed","scope":"synthetic original result"}\n'
            (original_directory / "result.json").write_bytes(prior_result)
            for phase in ("before", "prepare", "run"):
                pins.save(
                    directory,
                    phase + "-phase.json",
                    {
                        "phase": phase,
                        "status": "failed" if phase == "run" else "recorded",
                    },
                )
            pins.save(directory, "run-codes.json", [7, 0])
            with (
                mock.patch.object(
                    pins.sys, "argv", ["receipt", "finish", str(directory)]
                ),
                mock.patch.dict(pins.os.environ, {"RUNNER_TEMP": temporary}),
                mock.patch.object(pins, "source_snapshot") as snapshot,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(pins.main(), 1)
                snapshot.assert_not_called()
            receipt = pins.load(directory, "receipt.json")
            self.assertEqual(
                (receipt["status"], receipt["actual_test_exit_codes"]),
                ("failed", [7, 0]),
            )
            self.assertEqual(
                (original_directory / "result.json").read_bytes(), prior_result
            )


if __name__ == "__main__":
    unittest.main()
