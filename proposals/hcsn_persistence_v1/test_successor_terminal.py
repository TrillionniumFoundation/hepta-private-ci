"""Run the original eight terminal tests against a materialized successor.

Only the inherited test fixture is extended with the new persistence envelope.
The historical test file and materialized source remain unchanged. These are
explicit opaque-artifact fixtures, not serialized model or training evidence.
Use a fresh Python process with the successor's real Torch dependencies.
"""

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import unittest


def successor_suite(successor):
    """Load actual modules, preserving every original terminal-test method."""
    successor = Path(successor).resolve()
    fixture_path = successor / "test_c2_terminal_result.py"
    fixture_sha = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    if (
        fixture_sha
        != "b6504b36a5c90b481a1f48a5c9d7352ccaa6d031376448498ba3163045793a2f"
    ):
        raise ValueError("historical terminal fixture bytes differ")
    sys.path.insert(0, str(successor))
    for name in ("c2_io", "c2_runner", "c2_controller"):
        loaded = sys.modules.get(name)
        if loaded is not None and Path(loaded.__file__).resolve() != successor / (
            name + ".py"
        ):
            raise RuntimeError("use a fresh process for a different successor")
    spec = importlib.util.spec_from_file_location(
        "_hcsn_successor_original_terminal_fixture", fixture_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("c2_io", "c2_runner", "c2_controller"):
        if Path(sys.modules[name].__file__).resolve() != successor / (name + ".py"):
            raise RuntimeError("loaded a terminal dependency outside the successor")
    from hcsn_persistence_v1.atomic_io import identity
    from hcsn_persistence_v1.journal import (
        ReceiptJournal,
        process_identity,
        validate_closed_journal,
    )

    original_methods = unittest.defaultTestLoader.getTestCaseNames(
        module.TerminalResultTests
    )
    if len(original_methods) != 8:
        raise ValueError("expected the exact original eight terminal tests")

    class SuccessorTerminalTests(module.TerminalResultTests):
        def setUp(self):
            super().setUp()
            self.process["child_terminal_unknown"] = False
            # This opaque fixture's journal is owned by this test process.
            # It does not impersonate a native training child's identity.
            self.process["pid"] = os.getpid()
            self.process["process_identity"] = process_identity()
            self.result["persistence_schema"] = "hcsn-persistence-v1"
            self._replace_journal(
                [{"kind": "finished", "status": self.result["status"]}],
                self.result,
            )

        def tearDown(self):
            self.assertEqual(
                hashlib.sha256(fixture_path.read_bytes()).hexdigest(), fixture_sha
            )

        def _replace_journal(self, rows, result):
            # These paths are inside the inherited TemporaryDirectory only.
            # Rebuild fixtures without modifying any historical native output.
            view = self.output / "events.jsonl"
            index = self.output / "events.jsonl.receipt-index.json"
            records = self.output / "events.jsonl.records"
            view.unlink(missing_ok=True)
            index.unlink(missing_ok=True)
            if records.exists():
                shutil.rmtree(records)
            journal = ReceiptJournal(view)
            for row in rows:
                journal.append(row)
            journal.close()
            result["events"] = identity(view)
            result["events_receipt_index"] = identity(index)

        def write(self, value=None):
            result = copy.deepcopy(self.result if value is None else value)
            self._replace_journal(
                [{"kind": "finished", "status": result["status"]}], result
            )
            self.path.write_text(json.dumps(result))

        def write_journal_case(self, rows):
            result = copy.deepcopy(self.result)
            self._replace_journal(rows, result)
            self.path.write_text(json.dumps(result))

        def test_closed_empty_journal_cannot_establish_terminal_success(self):
            self.write_journal_case([])
            self.assert_failed_charged(self.gate())

        def test_closed_running_prefix_cannot_establish_terminal_success(self):
            self.write_journal_case([{"kind": "started", "status": "running"}])
            self.assert_failed_charged(self.gate())

        def test_terminal_payload_status_must_match_result(self):
            self.write_journal_case([{"kind": "finished", "status": "failed"}])
            self.assert_failed_charged(self.gate())

        def test_terminal_marker_must_be_last_and_unique(self):
            finished = {"kind": "finished", "status": "completed_development"}
            for rows in (
                [finished, {"kind": "started", "status": "running"}],
                [finished, finished],
            ):
                with self.subTest(rows=rows):
                    self.write_journal_case(rows)
                    self.assert_failed_charged(self.gate())

        def test_unknown_or_noninteger_exit_cannot_claim_terminal_completeness(self):
            for updates in (
                {"returncode": None, "child_terminal_unknown": True},
                {"returncode": False},
                {"returncode": 0.0},
                {"returncode": 2, "child_terminal_unknown": True},
                {"returncode": 2, "child_terminal_unknown": None},
                {"returncode": 2, "process_started": False},
                {"returncode": 2, "process_started": None},
                {"returncode": 2, "process_started": 1},
            ):
                with self.subTest(updates=updates):
                    process = dict(self.process, **updates)
                    result = copy.deepcopy(self.result)
                    result["status"] = (
                        "completed_development"
                        if process["returncode"] == 0
                        else "failed"
                    )
                    self.write(result)
                    row = self.gate(process)
                    self.assertEqual(row["status"], "failed_terminal_evidence")
                    self.assertFalse(row["terminal_evidence_complete"])
                    self.assertFalse(row["adequate"])
                    for name in (
                        "returncode",
                        "whole_process_wall_seconds",
                        "attempt_wrapper_wall_seconds",
                        "child_cpu_seconds",
                    ):
                        self.assertEqual(row[name], process[name])

        def test_outer_process_identity_must_match_the_journal_owner(self):
            self.write()
            absent_pid = copy.deepcopy(self.process)
            absent_pid.pop("pid")
            absent_identity = copy.deepcopy(self.process)
            absent_identity.pop("process_identity")
            absent_start = copy.deepcopy(self.process)
            absent_start["process_identity"].pop("start_ticks")
            different_start = copy.deepcopy(self.process)
            different_start["process_identity"]["start_ticks"] += 1
            different_boot = copy.deepcopy(self.process)
            boot = different_boot["process_identity"]["boot_id"]
            different_boot["process_identity"]["boot_id"] = (
                "1" if boot[0] == "0" else "0"
            ) + boot[1:]
            true_inner_pid = copy.deepcopy(self.process)
            true_inner_pid["process_identity"]["pid"] = True
            cases = {
                "missing_outer_pid": absent_pid,
                "missing_process_identity": absent_identity,
                "missing_start_ticks": absent_start,
                "different_start_ticks": different_start,
                "different_boot": different_boot,
                "boolean_outer_pid": dict(self.process, pid=True),
                "float_outer_pid": dict(self.process, pid=float(os.getpid())),
                "different_outer_pid": dict(self.process, pid=os.getpid() + 1),
                "boolean_owner_pid": true_inner_pid,
            }
            for name, process in cases.items():
                with self.subTest(identity_case=name):
                    row = self.gate(process)
                    self.assertEqual(row["status"], "failed_terminal_evidence")
                    self.assertFalse(row["terminal_evidence_complete"])
                    self.assertFalse(row["adequate"])
                    for field in (
                        "returncode",
                        "whole_process_wall_seconds",
                        "attempt_wrapper_wall_seconds",
                        "child_cpu_seconds",
                    ):
                        self.assertEqual(row[field], process[field])

        def test_complete_unique_terminal_journal_is_a_positive_control(self):
            self.write_journal_case(
                [
                    {"kind": "started", "status": "running"},
                    {"kind": "finished", "status": "completed_development"},
                ]
            )
            self.assertEqual(
                validate_closed_journal(self.output / "events.jsonl")["record_count"],
                2,
            )
            row = self.gate()
            self.assertEqual(row["status"], "completed")
            self.assertTrue(row["terminal_evidence_complete"])
            self.assertFalse(row["adequate"])

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SuccessorTerminalTests)
    if suite.countTestCases() != len(original_methods) + 7:
        raise AssertionError("the original terminal tests must all remain present")
    return suite


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--successor", required=True, type=Path)
    args = parser.parse_args()
    outcome = unittest.TextTestRunner(verbosity=2).run(successor_suite(args.successor))
    raise SystemExit(not outcome.wasSuccessful())
