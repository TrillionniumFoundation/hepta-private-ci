import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from . import coding_sft, data, e5_worker_control as control


class WorkerControlTests(unittest.TestCase):
    def test_intervals_include_queue_drain_and_exact_overlap(self):
        jobs = [dict(start_ns=12, end_ns=16), dict(start_ns=14, end_ns=20)]
        self.assertEqual(control.intervals(jobs, 10, 25), {0: 7, 1: 6, 2: 2})
        adjacent = [dict(start_ns=1, end_ns=3), dict(start_ns=3, end_ns=7)]
        self.assertEqual(control.intervals(adjacent, 1, 7), {1: 6})
        with self.assertRaises(ValueError):
            control.intervals(jobs, 13, 25)

    def test_budget_and_worker_axes(self):
        study = control.protocol()["human_study"]
        rows = control.allocation(study)
        self.assertEqual(len(rows), 16)
        self.assertEqual(
            {r["updates"] for r in rows if r["regime"] == "fixed_total"}, {64}
        )
        self.assertEqual(
            {r["updates_per_user"] for r in rows if r["regime"] == "fixed_per_user"},
            {32},
        )
        for r in rows:
            self.assertEqual(r["updates"], r["updates_per_user"] * r["users"])
        impossible = copy.deepcopy(study)
        impossible["regimes"]["fixed_total"] = 32
        with self.assertRaises(ValueError):
            control.allocation(impossible)

    def test_reader_accepts_native_json_and_rejects_modified_receipt(self):
        from .test_paired_cold import eval_task

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = eval_task(2, "later", 1)
            req = dict(parent={"v": 0}, candidate={"v": 1}, future=[task], retention=[])
            key = data.digest(req)
            receipts = []
            for arm in ("parent", "candidate"):
                folder = root / arm
                folder.mkdir()
                prediction = dict(
                    loaded_model_digest=data.digest(req[arm]),
                    answer="1",
                    input_tokens=1,
                    output_tokens=1,
                    pid=3,
                )
                row = dict(
                    panel="future",
                    task_sha256=data.digest(task),
                    prediction=prediction,
                    outcome=data.verify_answer(task, "1"),
                )
                receipt = dict(
                    arm=arm, request_sha256=key, row_hashes=[data.digest(row)], pid=3
                )
                coding_sft.write_new(folder / "0000.json", row)
                coding_sft.write_new(folder / "END.json", receipt)
                receipts.append(receipt)
            coding_sft.write_new(
                root / "RESULT.json",
                dict(
                    request_sha256=key,
                    cold_receipts=receipts,
                    counts={},
                    future_success_count_delta=0,
                    old_parent_successes_preserved=False,
                ),
            )
            self.assertEqual(len(control.inspect(root, req, key)["rows"]), 2)
            path = root / "candidate/0000.json"
            row = json.loads(path.read_text())
            row["prediction"]["output_tokens"] = 2
            path.write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, "retained paired row differs"):
                control.inspect(root, req, key)
