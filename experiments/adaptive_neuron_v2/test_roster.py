"""Behavioral guards for evidence pairing, immutable receipts and inference units."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .ledger import measured_stage, write_json_exclusive
from .roster import episode_plan, expected_roster, protocol, verify_roster
from .statistics import paired_interval


class RegisteredEvidenceTests(unittest.TestCase):
    def test_all_policy_comparisons_share_complete_evidence_streams(self):
        config = protocol()
        rows = expected_roster(config)
        grouped = {}
        for row in rows:
            key = row["seed"], row["split"]
            grouped.setdefault(key, row["plan"]["episodes"])
            self.assertEqual(row["plan"]["episodes"], grouped[key])
        self.assertEqual(sum(len(row["plan"]["episodes"]) for row in rows), 2880)
        for changed in (rows[:-1], [rows[0]] + rows[:-1], list(reversed(rows))):
            with self.assertRaisesRegex(ValueError, "missing, duplicate"):
                verify_roster(changed, rows)

    def test_seed_keyed_streams_ignore_policy_consumption(self):
        config = protocol()
        original = episode_plan(config, 601, "ood_test")
        consumed = copy.deepcopy(original)
        consumed[0]["observations"] = consumed[0]["observations"][:1]
        self.assertEqual(original, episode_plan(config, 601, "ood_test"))
        self.assertNotEqual(consumed, original)
        self.assertEqual([row["budget"] for row in original], [3.0] * 8 + [7.0] * 8)
        self.assertEqual(
            [row["budget"] for row in episode_plan(config, 607, "ood_test")],
            [7.0] * 8 + [3.0] * 8,
        )

    def test_confidence_intervals_use_seed_differences_and_preserve_negative_effects(
        self,
    ):
        differences = np.arange(-5, 5) / 100
        result = paired_interval(
            differences, family_alpha=0.05, comparisons=2, practical_effect=0.005
        )
        self.assertEqual(result["independent_seeds"], 10)
        self.assertAlmostEqual(result["confidence_level"], 0.975)
        self.assertLess(result["mean_difference"], 0)
        self.assertFalse(result["superiority_established"])
        self.assertLess(result["lower"], result["mean_difference"])
        self.assertGreater(result["upper"], result["mean_difference"])

    def test_late_failure_remains_visible_and_receipts_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(RuntimeError, "injected"):
                with measured_stage(
                    root / "stage", identity={"test": True}, scope="development fixture"
                ) as facts:
                    facts["completed_work"] = 3
                    raise RuntimeError("injected late failure")
            failed = json.loads((root / "stage/FAILED.json").read_text())
            self.assertFalse(failed["complete"])
            self.assertEqual(failed["facts"]["completed_work"], 3)
            with self.assertRaises(FileExistsError):
                write_json_exclusive(root / "stage/FAILED.json", {"complete": True})
            self.assertEqual(
                json.loads((root / "stage/FAILED.json").read_text()), failed
            )


if __name__ == "__main__":
    unittest.main()
