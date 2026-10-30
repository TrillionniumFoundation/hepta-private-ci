"""No incomplete panel may qualify; row/RNG/cost evidence must agree."""

from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .summarize import episode_cost_components, original_bytes, phase_cost_report, registered_tariff, run, validate_row


class DevelopmentSummaryTests(unittest.TestCase):
    def test_missing_matrix_produces_no_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "inputs").mkdir()
            result = run(root / "inputs", root / "analysis")
            self.assertFalse(result["complete_validated_panel"])
            self.assertEqual(result["missing_configurations"], [(17, 32), (17, 64), (29, 32), (29, 64)])
            self.assertIsNone(result["mechanism_gate"])
            self.assertIsNone(result["distillation_gate"])
            self.assertFalse(result["research_qualified"])

    def test_preserved_original_digest_is_checked_after_decompression(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b'{"result":"original"}\n'
            path = root / "RESULT.json.gz"
            path.write_bytes(gzip.compress(payload, mtime=0))
            manifest = {"preserved_originals": [{"source_path": "run/RESULT.json",
                "stored_path": path.name, "encoding": "gzip_original_bytes",
                "source_bytes": len(payload), "source_sha256": hashlib.sha256(payload).hexdigest()}]}
            self.assertEqual(original_bytes(root, manifest, "run/RESULT.json"), payload)
            path.write_bytes(gzip.compress(b'{"result":"tampered"}\n', mtime=0))
            with self.assertRaises(ValueError):
                original_bytes(root, manifest, "run/RESULT.json")

    def test_row_rejects_wrong_rng_and_optimistic_audit_cost(self):
        result = {"seed": 17, "width": 32, "profile_sha256": "a" * 64}
        artifacts = [[kind, "b" * 64] for kind in ("text", "image", "audio", "video")]
        row = {"seed": 17, "width": 32, "source": 0, "draw": 0, "arm": "hepta_dynamic_risk",
               "profile_sha256": "a" * 64, "source_namespace": "controller-v2-development",
               "artifacts": artifacts, "actions": ["shared", "stop"], "failure": None,
               "utility": 0.8, "cost": 0.1, "return": 0.7, "net_with_audit_close": 0.69,
               "audit_close_cost": 0.01, "cost_by_kind": {"shared": 0.1}}
        trajectory = {"seed": 200017, "profile_sha256": "a" * 64,
                      "source_id": "synthetic.controller-v2-development.0", "failure": None,
                      "actions": [{"action": "shared"}, {"action": "stop"}],
                      "outcome": {"artifact_sha256": artifacts, "delivered_utility": 0.8},
                      "actual_cost": 0.1, "net_return": 0.7}
        validate_row(row, trajectory, result, "hepta_dynamic_risk")
        changed = deepcopy(trajectory)
        changed["seed"] += 1
        with self.assertRaises(ValueError):
            validate_row(row, changed, result, "hepta_dynamic_risk")
        row["net_with_audit_close"] = 0.7
        with self.assertRaises(ValueError):
            validate_row(row, trajectory, result, "hepta_dynamic_risk")

    def test_phase_totals_are_not_double_counted_as_lifecycle_savings(self):
        phase = {"cpu_seconds": 10.0, "wall_seconds": 5.0, "physical_cost": 0.205}
        runner = {"cpu_seconds": 12.0, "wall_seconds": 6.0, "physical_cost": 0.246}
        result = {"phase_costs": {"distillation.training": phase}, "measured_runner_total": runner}
        process = {"child_cpu_seconds": 13.0, "supervisor_cpu_seconds": 1.0, "wall_seconds": 8.0,
                   "measured_process_tariff_cost": 0.288, "tariff": {"cpu_second": 0.02, "wall_second": 0.001}}
        report = phase_cost_report(result, process)
        self.assertAlmostEqual(report["outside_runner_including_startup_import_exit_and_supervisor"]["physical_cost"], 0.042)
        self.assertFalse(report["complete_lifecycle_savings_qualified"])
        result["phase_costs"]["duplicate"] = phase
        with self.assertRaises(ValueError):
            phase_cost_report(result, process)

    def test_fixed_fees_are_separated_from_actual_action_and_delivery_time(self):
        tariff = registered_tariff()
        action_time = 0.02 * 0.3 + 0.001 * 0.2
        fixed = tariff["shared"] + tariff["encode"] + tariff["delivery"]
        record = {"actions": [{"action": "shared", "cpu_seconds": 0.3, "wall_seconds": 0.2}],
                  "events": [{"selected_action": "shared", "costs": [{"amount": tariff["shared"] + tariff["encode"] + action_time}]},
                             {"selected_action": "delivery", "costs": [{"amount": tariff["delivery"] + 0.003}]}],
                  "actual_cost": fixed + action_time + 0.003}
        result = episode_cost_components(record, tariff)
        self.assertAlmostEqual(result["fixed_action_and_encode_service_fees"], fixed)
        self.assertAlmostEqual(result["episode_time_tariff_cost"], action_time + 0.003)
        record["events"][0]["costs"][0]["amount"] += 0.1
        with self.assertRaises(ValueError):
            episode_cost_components(record, tariff)


if __name__ == "__main__":
    unittest.main()
