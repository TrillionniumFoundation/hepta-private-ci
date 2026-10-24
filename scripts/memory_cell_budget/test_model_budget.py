"""No Torch: prove receipt-based settlement and failure charging with fake children."""

import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from budget_ledger import digest
from model_budget import ledger_for, model_call
from prepare_budget_study import common_budget


class ModelBudgetTests(unittest.TestCase):
    def test_supervised_tokens_are_not_counted_twice_and_terminal_never_reexecutes(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = ledger_for(
                root / "budget.sqlite3",
                "unit",
                {"common_budget": common_budget()},
                "0" * 64,
            )
            calls = []

            def child(*args, **kwargs):
                calls.append(args)
                path = root / "fake-child-receipt.json"
                path.write_text("{}")
                result = dict(
                    receipts=[dict(steps=3, input_tokens=40, supervised_tokens=10)],
                    worker_process_io_before_stdout=dict(rchar=12, wchar=8),
                )
                return dict(stdout=json.dumps(result), receipt_path=str(path))

            module = types.SimpleNamespace(ChildFailure=ValueError, run_child=child)
            with patch.dict("sys.modules", {"model_process": module}):
                result = model_call(
                    ledger,
                    "train",
                    dict(phase="arm"),
                    implementation=root,
                    directory=root / "first",
                    expected_updates=3,
                )
                self.assertEqual(result["actual"]["train_tokens"], 40)
                self.assertEqual(
                    result["supervised_tokens_subset_of_training_input_tokens"], 10
                )
                with self.assertRaises(ValueError):
                    model_call(
                        ledger,
                        "train",
                        dict(phase="arm"),
                        implementation=root,
                        directory=root / "replay",
                        expected_updates=3,
                    )
            self.assertEqual(len(calls), 1)
            self.assertEqual(ledger.snapshot()["executed_used"]["decoder_updates"], 3)

    def test_malformed_success_receipt_is_lost_work_not_measured_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = ledger_for(
                root / "budget.sqlite3",
                "unit",
                {"common_budget": common_budget()},
                "0" * 64,
            )

            def child(*args, **kwargs):
                path = root / "fake-child-receipt.json"
                path.write_text("{}")
                return dict(
                    stdout=json.dumps(
                        dict(
                            receipts=[
                                dict(steps=3, input_tokens=40, supervised_tokens=10)
                            ]
                        )
                    ),
                    receipt_path=str(path),
                )

            with patch.dict(
                "sys.modules",
                {
                    "model_process": types.SimpleNamespace(
                        ChildFailure=ValueError, run_child=child
                    )
                },
            ):
                with self.assertRaises(KeyError):
                    model_call(
                        ledger,
                        "train",
                        dict(phase="arm"),
                        implementation=root,
                        directory=root / "failed",
                        expected_updates=3,
                    )
            state = ledger.snapshot()
            self.assertTrue(state["closed"])
            self.assertEqual(state["used"]["decoder_updates"], 3)
            self.assertEqual(state["executed_used"]["decoder_updates"], 0)
            self.assertEqual(state["uncertain_work_charged"]["decoder_updates"], 3)


if __name__ == "__main__":
    unittest.main()
