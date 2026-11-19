"""Three manual service receipts; dataset, decoder fit and compilation mocked."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from independent import run
from independent.accounting import WorkLedger
from model import JointModel


class CalibrationRetentionTests(unittest.TestCase):
    def test_all_three_repeats_preserve_raw_reference_samples_and_cost_outliers(self):
        model = JointModel(202, 12, 192, hidden=4, seed=71)
        data = []
        for split in ("train", "validation"):
            data.append({"full": np.zeros((3, 202)), "low": np.zeros((3, 202)),
                "labels": np.arange(3), "source_ids": [split + str(i) for i in range(3)],
                "input_hashes": [split + "hash" + str(i) for i in range(3)], "split": split})
        reports = []
        for repeat in range(3):
            low, high = repeat + 1, 100
            per_cpu = [low, low, high]
            per_work = [11 + repeat, 11 + repeat, 13 + repeat]
            batches = [{"rows": rows, "cpu_ns": cpu, "wall_ns": cpu + 10,
                        "native_generation_and_ledger_cpu_ns": cpu // 2,
                        "output_encoding_and_ledger_cpu_ns": cpu - cpu // 2,
                        "remaining_service_cpu_ns": 0}
                       for rows, cpu in ((2, 2 * low), (1, high))]
            cost = {"batches": batches, "cpu_ns": sum(per_cpu), "wall_ns": sum(per_cpu) + 20,
                    "prepare_cpu_ns": 10 * (repeat + 1), "prepare_wall_ns": 20 * (repeat + 1),
                    "prepare": WorkLedger("hand-prepare").snapshot(),
                    "operator_totals": {"consumed_units": sum(per_work)},
                    "reference_full_cpu_ns": 1.0, "reference_full_work_units": 20,
                    "request_cap_units": 40, "runtime_batch_size": 2}
            reports.append({"per_row_cost": {"cpu_ns": per_cpu, "work_units": per_work,
                "wall_ns": [low + 5, low + 5, high + 10], "batch_index": [0, 0, 1],
                "output_bytes": [301, 302, 303]}, "cost": cost, "model_forwards": 3,
                "maximum_forwards_per_request": 1, "budget_violations": 0,
                "sampled_output": {"png_base64": "deliberately excluded from retention"}})
        plan = {"operator_units_per_system": 100000, "data_profile": {"hand_fixture": True},
                "calibration_per_class": 1, "calibration_salt": "hand", "calibration_rows": 3,
                "model_seeds": [11], "hidden": 4, "decoder_steps": 0, "pretrain_steps": 0,
                "static_modes": ["full"], "calibration_repeats": 3}
        decoder = SimpleNamespace(fit_decoder=Mock(return_value=0.0))
        objective = SimpleNamespace(step=Mock(side_effect=AssertionError("no training")))

        def compile_fixture(path):
            Path(path).write_bytes(b"hand library fixture; not executable")
            return {"library_path": str(path), "cached_compilation_used": False}

        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(run, "dataset", side_effect=data) as dataset, \
             patch.object(run, "stratified_indices", return_value=np.arange(3)), \
             patch.object(run, "calibration_manifest", return_value={"inputs_sha256": "hand"}), \
             patch.object(run, "counted_model_class", return_value=Mock(return_value=decoder)), \
             patch.object(run, "templates", return_value=np.zeros((12, 192))), \
             patch.object(run, "plain_copy", return_value=model), \
             patch.object(run, "CachedObjective", return_value=objective), \
             patch.object(run, "batch_validation", return_value=({"full": {}}, None)), \
             patch.object(run, "save_model", return_value={"file": "hand-base.npz"}), \
             patch("independent.native.compile_native", side_effect=compile_fixture), \
             patch("independent.evaluation.measure", side_effect=reports) as measure:
            ledger, _, _, _, common = run.prepare_shared(plan, Path(temporary), dict(plan))
        self.assertEqual([call.args[0] for call in dataset.call_args_list], ["train", "validation"])
        self.assertEqual(measure.call_count, 3)
        objective.step.assert_not_called()
        retained = common["calibrations"][11]
        self.assertEqual(retained["cpu_ns"]["full"], 3.0)
        self.assertNotEqual(retained["cpu_ns"]["full"], np.median([r["cost"]["cpu_ns"] / 3 for r in reports]))
        self.assertEqual(retained["prepare_cpu_samples_ns"]["full"], [10, 20, 30])
        self.assertEqual(ledger.totals["measured_service_requests"], 9)
        self.assertEqual(ledger.totals["serving_calibration_rows"], 9)
        self.assertEqual(ledger.consumed_units, 114)
        raw = retained["raw_repeats"]["full"]
        self.assertEqual([r["repeat"] for r in raw], [0, 1, 2])
        self.assertEqual(np.median([v for r in raw for v in r["per_row_cost"]["cpu_ns"]]), 3.0)
        for entry, original in zip(raw, reports):
            self.assertEqual(entry["per_row_cost"], original["per_row_cost"])
            self.assertEqual(entry["cost"], original["cost"])
            self.assertEqual((entry["sampling_seed"], entry["rows"], entry["mode"], entry["observe"]),
                             (11, 3, "full", False))
            self.assertEqual(entry["per_row_cost"]["cpu_ns"][-1], 100)
            self.assertNotIn("sampled_output", entry)
        json.dumps(retained, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
