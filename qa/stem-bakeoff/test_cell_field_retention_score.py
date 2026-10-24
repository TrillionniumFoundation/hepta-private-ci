"""Fixed estimand and pre-label identity gates on fabricated probability arrays."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

import cell_field_retention_score as scoring
from cell_learning_models import canonical


def records():
    return [{"seed": s, "head": h, "arm": a, "initial_index": i, "status": "completed"}
            for i, (s, h) in enumerate((s, h) for s in scoring.SEEDS for h in scoring.HEADS)
            for a in scoring.ARMS]


class FrozenScoreTests(unittest.TestCase):
    def setUp(self):
        self.records = records()
        self.final, self.initial = np.full((18, 480, 4), 0.25), np.full((6, 480, 4), 0.25)
        self.roles = {}
        start = 0
        for role, count in scoring.ROLES.items():
            indices = np.arange(start, start + count)
            self.roles[role] = (indices, indices % 4)
            start += count

    def test_equal_predictions_do_not_pass_strict_future_gain_gate(self):
        result = scoring.contrasts(self.final, self.initial, self.records, self.roles)
        for value in result.values():
            self.assertEqual(value["primary_future_nll_hinge_minus_legacy"]["ci95"], [0, 0])
            self.assertFalse(value["future_gate"])
            self.assertTrue(value["retention_gate"])
            self.assertFalse(value["joint_gates_pass"])

    def test_retention_gate_uses_original_warmup_not_a_degraded_comparator(self):
        labels = np.arange(480) % 4

        def probabilities(correct):
            value = np.full((480, 4), (1 - correct) / 3)
            value[np.arange(480), labels] = correct
            return value

        for i, record in enumerate(self.records):
            self.final[i] = probabilities({"zero": 0.5, "legacy_full_quadratic": 0.6,
                                          "retention_hinge_suffix": 0.7}[record["arm"]])
        self.initial[:] = probabilities(0.8)
        result = scoring.contrasts(self.final, self.initial, self.records, self.roles)
        for value in result.values():
            self.assertTrue(value["future_gate"])
            self.assertLess(value["secondary_old_test_nll_hinge_minus_legacy"]["estimate"], 0)
            self.assertAlmostEqual(value["retention_old_test_nll_hinge_minus_original_warmup"]["estimate"],
                                   np.log(0.8 / 0.7), places=14)
            self.assertFalse(value["retention_gate"])
            self.assertFalse(value["joint_gates_pass"])

    def test_missing_condition_nan_and_wrong_initial_identity_reject(self):
        for kind in ("failed", "nan", "initial"):
            records_copy, probabilities = copy.deepcopy(self.records), self.final.copy()
            if kind == "failed":
                records_copy[-1]["status"] = "failed"
            elif kind == "nan":
                probabilities[0, 0, 0] = np.nan
            else:
                records_copy[-1]["initial_index"] = 0
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                scoring.contrasts(probabilities, self.initial, records_copy, self.roles)

    def test_incomplete_sealed_census_never_opens_or_requires_new_gold_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "data"
            data.mkdir()  # Deliberately no final_labels.json exists.
            records_copy = copy.deepcopy(self.records)
            records_copy[-1]["status"] = "failed"
            plan = {"scorer_source_sha256": hashlib.sha256(Path(scoring.__file__).read_bytes()).hexdigest()}
            (root / "protocol.json").write_bytes(canonical(plan) + b"\n")
            plan_sha = hashlib.sha256((root / "protocol.json").read_bytes()).hexdigest()
            summary = {"protocol_sha256": plan_sha, "final_labels_opened": False,
                       "completed_conditions": 17, "records": records_copy}
            (root / "summary.json").write_bytes(canonical(summary) + b"\n")
            (root / "input_manifest.json").write_bytes(b"{}\n")
            (root / "frozen_predictions.npz").write_bytes(b"not parsed before complete census")
            seal = {"schema": "hepta.cell-retention.prediction-seal.v1", "final_labels_opened": False}
            for name, key in (("summary.json", "summary_sha256"), ("frozen_predictions.npz", "predictions_sha256"),
                              ("input_manifest.json", "input_manifest_sha256"), ("protocol.json", "protocol_sha256")):
                seal[key] = hashlib.sha256((root / name).read_bytes()).hexdigest()
            (root / "seal.json").write_bytes(canonical(seal) + b"\n")
            expected = hashlib.sha256((root / "seal.json").read_bytes()).hexdigest()
            result = scoring.score(root, data, root / "result.json", expected_seal_sha256=expected)
            self.assertEqual(result["status"], "blocked_incomplete_conditions")
            self.assertFalse(result["final_labels_opened"])
            self.assertEqual(json.loads((root / "result.json").read_bytes()), result)
            with self.assertRaises(ValueError):
                scoring.score(root, data, root / "another.json", expected_seal_sha256="0" * 64)


if __name__ == "__main__":
    unittest.main()
