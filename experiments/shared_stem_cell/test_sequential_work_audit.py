"""Fail-closed physical-work controls; synthetic profiles are not model evidence."""
from copy import deepcopy
import unittest

from experiments.shared_stem_cell import sequential_work_audit as a


class SequentialWorkTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"cell": 0}, {"cell": 1}, {"cell": 0}, {"cell": 1}]
        self.lock = {
            "physical_work_profile": a.SCHEMA,
            "source_simulated_encoder": False,
            "profile": {"width": 384},
            "expected_stem_sha256": "a" * 64,
            "selected": "bank", "scope": "test-scope",
        }
        self.raw = {
            "selected": "bank", "feature_sha256": "b" * 64,
            "encoding": {
                "simulated_encoder": False, "model_digest": "a" * 64,
                "cache_object_overhead_measured": False,
                "encoder_forward_calls": 1, "cache_reuses": 0,
                "requests": 4, "retained_result_tensor_bytes": 6144,
                "cache_retained_tensor_bytes": 0,
            },
            "inference_costs": {},
        }
        for arm in a.ARMS:
            calls = a._calls(arm, self.rows)
            self.raw["inference_costs"][arm] = {
                "calls": calls, "head_forward_calls": len(calls),
                "head_rows_processed": sum(len(c["rows"]) for c in calls),
                "encoder_calls": 0, "active_flops": None,
                "energy_joules": None, "wall_ns": 100, "process_cpu_ns": 90,
            }

    def test_complete_cost_census_and_repeated_record_sum(self):
        receipt = a.validate_batch(self.rows, self.raw, self.lock)
        self.assertEqual(receipt["encoder_forward_calls"], 1)
        self.assertEqual(receipt["head_work"]["residual_corrected"]["head_rows_processed"], 8)
        total = a.aggregate([receipt, receipt])
        self.assertEqual(total["encoder_input_rows"], 8)
        self.assertEqual(total["per_arm_head_forward_calls"]["residual_corrected"], 6)
        self.assertIsNone(total["active_flops"])
        self.assertFalse(total["production_accepted"])

    def test_wrong_routing_double_count_and_fabricated_resource_reject(self):
        errors = (
            ("bank", "calls", [{"component": "bank-0", "rows": [0, 1, 2, 3]}]),
            ("residual_corrected", "head_rows_processed", 4),
            ("shared", "head_forward_calls", 0),
            ("linear_distilled", "active_flops", 1),
        )
        for arm, key, invalid in errors:
            with self.subTest(arm=arm, key=key):
                record = deepcopy(self.raw)
                record["inference_costs"][arm][key] = invalid
                with self.assertRaises(a.InputError):
                    a.validate_batch(self.rows, record, self.lock)

    def test_encoder_and_immutable_selected_profile_cannot_drift(self):
        errors = (
            ("encoder_forward_calls", 0), ("requests", 3),
            ("retained_result_tensor_bytes", 0),
            ("model_digest", "c" * 64), ("simulated_encoder", True),
            ("cache_object_overhead_measured", True),
        )
        for key, invalid in errors:
            with self.subTest(key=key):
                record = deepcopy(self.raw)
                record["encoding"][key] = invalid
                with self.assertRaises(a.InputError):
                    a.validate_batch(self.rows, record, self.lock)
        record = deepcopy(self.raw)
        record["selected"] = "shared"
        with self.assertRaises(a.InputError):
            a.validate_batch(self.rows, record, self.lock)

    def test_preflight_and_cross_scope_aggregation_reject(self):
        for rows in ([], [{"cell": 0}, {"cell": True}],
                     self.rows + [{"cell": 3}]):
            with self.subTest(rows=rows), self.assertRaises(a.InputError):
                a.validate_batch(rows, self.raw, self.lock)
        receipt = a.validate_batch(self.rows, self.raw, self.lock)
        mixed = deepcopy(receipt)
        mixed["scope"] = "other"
        with self.assertRaises(a.InputError):
            a.aggregate([receipt, mixed])


if __name__ == "__main__":
    unittest.main()
