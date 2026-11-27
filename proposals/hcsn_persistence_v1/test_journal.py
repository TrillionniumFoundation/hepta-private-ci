"""Receipt integrity and abrupt process termination; not power-loss tests."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from time import perf_counter, process_time
import unittest
from unittest.mock import patch

from proposals.hcsn_persistence_v1.atomic_io import (
    atomic_publish,
    canonical_json,
    identity,
)
from proposals.hcsn_persistence_v1.journal import (
    ReceiptJournal,
    process_identity,
    read_receipts,
    validate_closed_journal,
    validate_terminal_journal,
)


class ReceiptJournalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.view = Path(self.temporary.name) / "events.jsonl"
        self.records = self.view.with_name(self.view.name + ".records")
        self.index = self.view.with_name(self.view.name + ".receipt-index.json")

    def test_empty_close_and_second_close_are_read_only(self):
        journal = ReceiptJournal(self.view)
        result = journal.close()
        self.assertEqual(result["record_count"], 0)
        self.assertIsNone(result["head_sha256"])
        self.assertEqual(self.view.read_bytes(), b"")
        self.assertEqual(
            result["owner_identity"], identity(self.records / "owner.json")
        )
        before = self.index.stat().st_mtime_ns
        with patch("proposals.hcsn_persistence_v1.journal.atomic_publish") as publish:
            self.assertEqual(journal.close(), result)
            publish.assert_not_called()
        self.assertEqual(self.index.stat().st_mtime_ns, before)
        with self.assertRaises(ValueError):
            journal.append({"later": True})

    def test_concurrent_append_binds_all_rows_and_exact_derived_view(self):
        journal = ReceiptJournal(self.view)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: journal.append({"sample": i}), range(12)))
        index = journal.close()
        self.assertEqual(validate_closed_journal(self.view), index)
        state = read_receipts(self.view)
        self.assertTrue(state["journal_closed"])
        self.assertFalse(state["all_terminal_established"])
        rows = [r["payload"] for r in state["receipts"]]
        self.assertEqual(sorted(r["sample"] for r in rows), list(range(12)))
        self.assertEqual(self.view.read_bytes(), b"".join(map(canonical_json, rows)))

    def test_index_counts_require_exact_json_numeric_types(self):
        index = ReceiptJournal(self.view).close()
        for invalid in (False, 0.0):
            with self.subTest(invalid=invalid):
                self.index.write_bytes(
                    canonical_json({**index, "record_count": invalid})
                )
                with self.assertRaises(ValueError):
                    validate_closed_journal(self.view)

    def test_terminal_semantics_require_one_last_matching_finished_event(self):
        running, done = {"kind": "running"}, {"kind": "finished", "status": "completed"}
        cases = [
            ([], "completed", False),
            ([running], "completed", False),
            ([{"kind": "finished", "status": "failed"}], "completed", False),
            ([done, done], "completed", False),
            ([done, running], "completed", False),
            ([done], True, False),
            ([{"kind": "finished", "status": 1}], "1", False),
            ([running, done], "completed", True),
        ]
        for rows, expected, accepted in cases:
            with (
                self.subTest(rows=rows, expected=expected),
                tempfile.TemporaryDirectory() as tmp,
            ):
                view = Path(tmp) / "events.jsonl"
                journal = ReceiptJournal(view)
                for row in rows:
                    journal.append(row)
                index = journal.close()
                if accepted:
                    self.assertEqual(validate_terminal_journal(view, expected), index)
                else:
                    with self.assertRaises(ValueError):
                        validate_terminal_journal(view, expected)

    def test_terminal_owner_matches_the_observed_process_with_exact_types(self):
        owner = process_identity(os.getpid())
        self.assertEqual(owner, process_identity())
        journal = ReceiptJournal(self.view)
        journal.append({"kind": "finished", "status": "completed"})
        index = journal.close()
        self.assertEqual(
            validate_terminal_journal(self.view, "completed", owner), index
        )
        bad = [
            {**owner, "pid": owner["pid"] + 1},
            {**owner, "start_ticks": owner["start_ticks"] + 1},
            {**owner, "boot_id": "00000000-0000-0000-0000-000000000000"},
            {**owner, "pid": True},
            {**owner, "start_ticks": float(owner["start_ticks"])},
            {key: value for key, value in owner.items() if key != "boot_id"},
        ]
        for expected in bad:
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                validate_terminal_journal(self.view, "completed", expected)
        for pid in (True, 0, -1, 1.0, "1"):
            with self.subTest(pid=pid), self.assertRaises(ValueError):
                process_identity(pid)

    def test_torn_view_does_not_replace_authority_and_closed_gate_rejects_it(self):
        journal = ReceiptJournal(self.view)
        journal.append({"status": "running"})
        journal.close()
        self.view.write_bytes(b'{"status":')
        self.assertEqual(len(read_receipts(self.view)["receipts"]), 1)
        with self.assertRaises(ValueError):
            validate_closed_journal(self.view)
        with self.assertRaises(ValueError):
            journal.close()
        self.assertEqual(self.view.read_bytes(), b'{"status":')

    def test_chain_rejects_gap_duplicate_tamper_wrong_owner_and_truncated_tail(self):
        for failure in (
            "gap",
            "duplicate",
            "payload",
            "owner",
            "torn",
            "tail",
            "open-tail",
        ):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                view = Path(tmp) / "events.jsonl"
                journal = ReceiptJournal(view)
                for i in range(3):
                    journal.append({"sample": i})
                if failure != "open-tail":
                    journal.close()
                records = view.with_name(view.name + ".records")
                files = [records / f"{i:020d}.json" for i in range(3)]
                if failure in ("gap", "tail", "open-tail"):
                    files[1 if failure == "gap" else 2].unlink()
                elif failure == "duplicate":
                    files[1].write_bytes(files[0].read_bytes())
                elif failure == "payload":
                    row = json.loads(files[1].read_bytes())
                    row["payload"]["sample"] = 99
                    files[1].write_bytes(canonical_json(row))
                elif failure == "owner":
                    owner_path = records / "owner.json"
                    row = json.loads(owner_path.read_bytes())
                    row["pid"] += 1
                    owner_path.write_bytes(canonical_json(row))
                else:
                    files[2].write_bytes(b'{"payload":')
                with self.assertRaises(ValueError):
                    if failure == "open-tail":
                        journal.close()
                    else:
                        read_receipts(view)

    def test_uncertain_append_is_not_retried_and_close_rebuilds_committed_view(self):
        for failure in ("view", "post-commit"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                journal = ReceiptJournal(Path(tmp) / "events.jsonl")

                def after_publish(*args, **kwargs):
                    atomic_publish(*args, **kwargs)
                    raise OSError("publication return lost")

                target = patch.object(
                    journal, "_append_view", side_effect=OSError("view")
                )
                if failure == "post-commit":
                    target = patch(
                        "proposals.hcsn_persistence_v1.journal.atomic_publish",
                        side_effect=after_publish,
                    )
                with target, self.assertRaises(OSError):
                    journal.append({"sample": 1})
                with self.assertRaises(ValueError):
                    journal.append({"sample": 1})
                self.assertEqual(journal.close()["record_count"], 1)
                self.assertEqual(
                    journal.view.read_bytes(), canonical_json({"sample": 1})
                )

    def test_three_thousand_events_preserve_count_order_and_measured_cost(self):
        journal = ReceiptJournal(self.view)
        wall, cpu = perf_counter(), process_time()
        for sample in range(3000):
            journal.append({"sample": sample})
        append_wall = perf_counter() - wall
        index = journal.close()
        self.assertEqual(index["record_count"], 3000)
        rows = [json.loads(line) for line in self.view.read_text().splitlines()]
        self.assertEqual([row["sample"] for row in rows], list(range(3000)))
        print(
            "HCSN_JOURNAL_COST "
            + json.dumps(
                dict(
                    events=3000,
                    append_wall=append_wall,
                    total_wall=perf_counter() - wall,
                    cpu=process_time() - cpu,
                )
            )
        )

    def test_abrupt_exit_after_receipt_commit_preserves_prefix_without_terminal(self):
        program = """
import os, sys
from proposals.hcsn_persistence_v1.journal import ReceiptJournal
journal = ReceiptJournal(sys.argv[1])
journal._append_view = lambda raw: os._exit(73)
journal.append({'status': 'running'})
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", program, str(self.view)],
            cwd=Path(__file__).resolve().parents[2],
            check=False,
        )
        self.assertEqual(result.returncode, 73)
        self.assertFalse(self.view.exists())
        (self.records / ".00000000000000000001.json.uncommitted.tmp").write_bytes(b"{")
        state = read_receipts(self.view)
        self.assertEqual(len(state["receipts"]), 1)
        self.assertEqual(state["pending_temporary_files"], 1)
        self.assertFalse(state["journal_closed"])
        self.assertFalse(state["all_terminal_established"])
        with self.assertRaises(ValueError):
            validate_closed_journal(self.view)
        with self.assertRaises(FileExistsError):
            ReceiptJournal(self.view)
        self.assertEqual(len(read_receipts(self.view)["receipts"]), 1)

    def test_child_process_cannot_append_under_the_original_owner(self):
        journal = ReceiptJournal(self.view)
        child = os.fork()
        if child == 0:
            try:
                journal.append({"child": True})
            except ValueError:
                os._exit(0)
            os._exit(91)
        _, status = os.waitpid(child, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        self.assertEqual(journal.close()["record_count"], 0)


if __name__ == "__main__":
    unittest.main()
