"""Comparison and failure-accounting tests; fixtures are not training evidence."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .. import data
from ..coding_sft import file_hash, write_new
from ..test_data import record
from . import round03_cli
from .round03_jobs import compare_cold
from .round03_plan import check_comparison, compare_freezes, make_comparison, panels
from .test_onpolicy_flow import FixtureBackend


def comparison_fixture():
    context = {
        "records": [
            record(index, "train" if index <= 6 else "selection")
            for index in range(1, 10)
        ]
    }
    manifests = {
        mode: {"fixture": mode}
        for mode in ("final_answer", "trajectory", "controlled_correction")
    }
    return context, manifests, FixtureBackend()


class ComparisonTests(unittest.TestCase):
    def test_three_controls_share_initial_weights_and_reject_a_different_arm(self):
        context, manifests, backend = comparison_fixture()
        frozen = make_comparison(context, manifests, backend, "comparison-unit", {})
        freezes = frozen["E2"]["freezes"]
        compare_freezes(freezes)
        self.assertEqual(
            {v["initial_model_digest"] for v in freezes.values()},
            {data.digest(manifests["final_answer"])},
        )
        changed = copy.deepcopy(freezes)
        changed["controlled"]["initial_model_digest"] = data.digest(
            manifests["controlled_correction"]
        )
        with self.assertRaisesRegex(ValueError, "initial_model_digest"):
            compare_freezes(changed)

    def test_replayed_data_never_becomes_new_C_or_a_new_source(self):
        context, manifests, backend = comparison_fixture()
        frozen = make_comparison(context, manifests, backend, "comparison-unit", {})
        self.assertEqual(frozen["independent_sample_increment"], 0)
        self.assertFalse(frozen["new_C"])
        altered = copy.deepcopy(context)
        altered["records"][6]["exposure"] = "unseen"
        with self.assertRaisesRegex(ValueError, "exposed development"):
            panels(altered)
        altered = copy.deepcopy(context)
        altered["records"][6]["split"] = "train"
        with self.assertRaisesRegex(ValueError, "A6/B3"):
            panels(altered)

    def test_changed_context_or_execution_source_cannot_reuse_comparison(self):
        context, manifests, backend = comparison_fixture()
        inventory = {"entry": "a" * 64}
        frozen = make_comparison(
            context, manifests, backend, "comparison-unit", inventory
        )
        check_comparison(frozen, context, manifests, backend, inventory)
        altered = copy.deepcopy(context)
        altered["records"][8]["task"]["input"] += " changed"
        with self.assertRaisesRegex(ValueError, "comparison source"):
            check_comparison(frozen, altered, manifests, backend, inventory)
        with self.assertRaisesRegex(ValueError, "comparison source"):
            check_comparison(frozen, context, manifests, backend, {"entry": "b" * 64})

    def test_cold_use_needs_another_process_and_compares_actual_requests_and_answers(
        self,
    ):
        primary = {
            "phase": "primary",
            "pid": 11,
            "model_digest": "a" * 64,
            "comparison_digest": "b" * 64,
            "panel_digests": {},
            "source_inventory": {},
            "rows": [
                {
                    "task_id": "one",
                    "record_id": "one",
                    "success": True,
                    "first_attempt_success": True,
                    "steps": [
                        {
                            "request_sha256": "c" * 64,
                            "output": {
                                "answer": "answer",
                                "input_tokens": 4,
                                "output_tokens": 1,
                            },
                            "verification": {"success": True},
                        }
                    ],
                }
            ],
        }
        cold = {**copy.deepcopy(primary), "phase": "cold", "pid": 12}
        self.assertTrue(
            compare_cold(primary, cold)["same_answer_and_request_observations"]
        )
        cold["rows"][0]["steps"][0]["request_sha256"] = "d" * 64
        self.assertFalse(
            compare_cold(primary, cold)["same_answer_and_request_observations"]
        )
        cold["pid"] = primary["pid"]
        with self.assertRaisesRegex(ValueError, "separate observed process"):
            compare_cold(primary, cold)

    def test_failed_owned_worker_preserves_intent_and_refuses_automatic_rerun(self):
        module = round03_cli
        entry = Path(module.__file__)
        context, manifests, backend = comparison_fixture()
        gate = {
            "status": "PASSED",
            "source_inventory": backend.sources(),
            "scope": "scripted engineering receipt fixture; no numerical pass claim",
        }
        inventory = {
            "round03_cli.py": file_hash(entry),
            "engineering_gate_digest": data.digest(gate),
        }
        frozen = make_comparison(
            context, manifests, backend, "comparison-unit", inventory
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_new(directory / "COMPARISON.json", frozen)
            write_new(directory / "ENGINEERING_GATE.json", gate)
            with patch(
                "cell_experiments.online_v4.round03_jobs.run_e2",
                side_effect=RuntimeError("intentional fixture stop"),
            ) as worker:
                with self.assertRaisesRegex(RuntimeError, "intentional fixture"):
                    module.execute(
                        directory, directory, context, manifests, backend, "e2-teacher"
                    )
                receipt = data._parse(
                    (directory / "worker-receipts/e2-teacher/FAILED.json").read_bytes()
                )
                self.assertFalse(receipt["automatic_retry"])
                self.assertFalse(receipt["call_totals_complete"])
                with self.assertRaises(FileExistsError):
                    module.execute(
                        directory, directory, context, manifests, backend, "e2-teacher"
                    )
                self.assertEqual(worker.call_count, 1)


if __name__ == "__main__":
    unittest.main()
