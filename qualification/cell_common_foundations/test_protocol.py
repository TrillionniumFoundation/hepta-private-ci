import tempfile
import unittest
from pathlib import Path

from qualification.cell_common_foundations.protocol import (
    AttemptSpec,
    canonical_digest,
    compare_profiles,
    cost_observation,
    source_inventory,
    summarize_attempts,
)


class ProtocolTests(unittest.TestCase):
    def test_missing_and_failed_attempts_remain_in_denominator(self):
        roster = [
            AttemptSpec("a", "credit", "bptt", 1),
            AttemptSpec("b", "credit", "diffusion", 1),
            AttemptSpec("c", "credit", "bptt", 2),
        ]
        records = [
            dict(
                attempt_id="a",
                family="credit",
                method="bptt",
                seed=1,
                status="completed",
                result={"loss": 0.3},
            ),
            dict(
                attempt_id="b",
                family="credit",
                method="diffusion",
                seed=1,
                status="failed",
                reason="nonfinite",
            ),
        ]
        result = summarize_attempts(roster, records)
        self.assertEqual(
            result["counts"],
            {"completed": 1, "failed": 1, "unstarted": 1, "running": 0, "cancelled": 0},
        )
        self.assertEqual(result["missing_attempt_ids"], ["c"])
        self.assertEqual(result["planned_seed_count"], 2)
        self.assertEqual(
            result["completed_seed_count_by_family_method"],
            {"credit/bptt": 1, "credit/diffusion": 0},
        )
        self.assertFalse(result["complete"])
        with self.assertRaises(ValueError):
            summarize_attempts(roster, records + records[:1])

    def test_empty_or_nonfinite_completion_is_rejected(self):
        spec = AttemptSpec("a", "credit", "bptt", 1)
        row = dict(
            attempt_id="a", family="credit", method="bptt", seed=1, status="completed"
        )
        with self.assertRaises(ValueError):
            summarize_attempts([spec], [row])
        row["result"] = {}
        with self.assertRaises(ValueError):
            summarize_attempts([spec], [row])
        row["result"] = {"loss": float("nan")}
        with self.assertRaises(ValueError):
            summarize_attempts([spec], [row])

    def test_equal_profiles_do_not_hide_training_opportunity_mismatch(self):
        profile = dict(
            encoder_digest="encoder",
            head_initial_digest="head",
            data_split_digest="split",
            ndu_profile_digest="ndu",
            training_observations=12,
            optimizer_updates=4,
            tuning_trials=0,
            seed=2,
            device_profile="cpu",
            precision="fp64",
            training_scope="head_only",
        )
        self.assertTrue(compare_profiles(profile, dict(profile))["matched"])
        changed = dict(profile, training_observations=11)
        self.assertEqual(
            compare_profiles(profile, changed),
            {"matched": False, "mismatches": ["training_observations"]},
        )
        changed.pop("ndu_profile_digest")
        with self.assertRaises(ValueError):
            compare_profiles(profile, changed)

    def test_unknown_energy_is_not_zero_and_overlapping_cost_is_rejected(self):
        result = cost_observation(
            wall_seconds=2, cpu_seconds=1, components={"training": 1.5}
        )
        self.assertIsNone(result["energy_joules"])
        self.assertEqual(result["unallocated_wall_seconds"], 0.5)
        with self.assertRaises(ValueError):
            cost_observation(wall_seconds=2, cpu_seconds=1, energy_joules=3)
        with self.assertRaises(ValueError):
            cost_observation(
                wall_seconds=2, cpu_seconds=1, components={"train": 1.5, "nested": 1}
            )
        with self.assertRaises(ValueError):
            cost_observation(wall_seconds=True, cpu_seconds=1)

    def test_source_binding_changes_with_bytes_and_refuses_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "code.py").write_text("a = 1\n")
            first = source_inventory(root, ["code.py"])
            (root / "code.py").write_text("a = 2\n")
            second = source_inventory(root, ["code.py"])
            self.assertNotEqual(first["digest"], second["digest"])
            with self.assertRaises(ValueError):
                source_inventory(root, ["../code.py"])
        self.assertEqual(
            canonical_digest({"a": 1, "b": 2}), canonical_digest({"b": 2, "a": 1})
        )


if __name__ == "__main__":
    unittest.main()
