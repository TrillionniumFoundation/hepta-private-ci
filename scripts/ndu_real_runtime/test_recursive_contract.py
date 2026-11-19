"""Pure-Python conformance for recursive decisions and explicit episode chains."""

import copy
from dataclasses import asdict
import json
from pathlib import Path
import unittest

from .controllers import ControlPlan, Controller, Forecast, PublicState
from .objective import canonical_sha, certainty_equivalent, edge_value, utility_profile
from .training import validate_record
from .trajectory import (
    V2_SCHEMA,
    episode_groups,
    validate_chains,
    memory_replay_metadata,
)


def numerical_records(plan):
    """Synthetic numerical fixtures only; not independent task/effect evidence."""
    rows = []
    features = [
        [[0.01 * (step + 1)] * 126, [-0.02 * (step + 1)] * 126] for step in range(3)
    ]
    metadata = [
        [
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            1.0,
            float(step > 0),
            float(step > 1),
            0.0,
            0.0,
            0.1,
            step / 8,
            (10 - step) / 10,
            0.0,
        ]
        for step in range(3)
    ]
    for step, action in enumerate(("PREPARE_ROI", "READ_ROI", "STOP")):
        row = {
            "schema": V2_SCHEMA,
            "record_id": "numerical-fixture/" + str(step),
            "episode_id": "numerical-fixture",
            "origin_run_id": "not-real-evidence",
            "source_group": "fixture",
            "split": "train",
            "source_size": {"width": 100, "height": 100},
            "candidate_features": features[step],
            "public_metadata": metadata[step],
            "candidate_metadata": [
                {
                    "text": text,
                    "bbox": [0, 0, 40, 20],
                    "origin": "registered_public_text",
                }
                for text in ("ACME", "OTHER")
            ],
            "reference_field": "company",
            "expected_text": "ACME",
            "target_boxes": [[0, 0, 40, 20]],
            "action": action,
            "next_candidate_features": features[step + 1] if step < 2 else None,
            "next_public_metadata": metadata[step + 1] if step < 2 else None,
            "before_score": [0.2, 0.25, 0.8][step],
            "after_score": [0.25, 0.8, 0.8][step],
            "duration_seconds": 0.1,
            "execution_status": "completed",
            "terminal_reason": "actor_stop" if step == 2 else None,
            "episode_step": step,
            "previous_record_sha256": rows[-1]["record_sha256"] if rows else None,
            "remaining_seconds": float(10 - step),
            "memory_mode": plan.memory_mode,
            "legal_actions": [
                "PREPARE_ROI",
                *(["READ_ROI"] if step else []),
                "WRITE_TEXT",
                "RENDER_IMAGE",
                "STOP",
            ],
            "utility_profile_sha256": canonical_sha(utility_profile(plan)),
            "rubric_sha256": "a" * 64,
            "behavior_control_profile_sha256": canonical_sha(asdict(plan)),
        }
        row["record_sha256"] = canonical_sha(row)
        rows.append(row)
    return rows


class RecursiveContractTests(unittest.TestCase):
    def test_golden_lotteries_and_actual_duration_discount(self):
        golden = json.loads(
            Path(__file__).with_name("finite_entropic_golden.json").read_text()
        )
        for row in golden["certainty_equivalent"]:
            self.assertAlmostEqual(
                certainty_equivalent(row["values"], row["probabilities"], row["risk"]),
                row["expected"],
                places=13,
            )
        row = golden["duration_branch"]
        plan = ControlPlan(
            **{
                key: row[key]
                for key in ("risk", "discount_per_second", "latency_weight")
            }
        )
        values = [
            edge_value(duration, continuation, plan)
            for duration, continuation in zip(
                row["durations_seconds"], row["continuations"]
            )
        ]
        self.assertAlmostEqual(
            certainty_equivalent(values, row["probabilities"], plan.risk),
            row["expected"],
            places=13,
        )
        with self.assertRaises(ValueError):
            certainty_equivalent([1, 2], [0.1, 0.1], 0.25)
        for risk in (1e-300, 1e-20, 1e-12, 1e-6):
            value = certainty_equivalent([0.2, 0.8], [0.25, 0.75], risk)
            self.assertLessEqual(abs(value - 0.65), risk * 0.04 + 1e-14)

    def test_nested_decision_and_cap_are_executed(self):
        class Predictor:
            def utility(self, state):
                return state.features[0]

            def forecast(self, state, action, particles, seed):
                value = 0.3 if action == "PREPARE_ROI" else 0.9
                return [
                    Forecast(
                        (value,),
                        value,
                        1.0,
                        1.0,
                        ("READ_ROI", "STOP") if action == "PREPARE_ROI" else ("STOP",),
                    )
                ]

        state = PublicState((0.2,), 5.0, 0, ("PREPARE_ROI", "STOP"))
        action, receipt = Controller("ndu", Predictor(), ControlPlan(horizon=2)).choose(
            state
        )
        self.assertEqual(action, "PREPARE_ROI")
        self.assertAlmostEqual(receipt["predicted_values"][action], 0.88)
        _, limited = Controller(
            "ndu", Predictor(), ControlPlan(horizon=2, max_forecasts=1)
        ).choose(state)
        self.assertEqual(limited["forecast_calls"], 1)
        self.assertTrue(limited["planner_budget_exhausted"])

    def test_chains_bind_successors_and_reject_missing_prefix(self):
        rows = numerical_records(ControlPlan())
        for row in rows:
            validate_record(row)
        self.assertEqual(validate_chains(list(reversed(rows))), 1)
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            validate_chains(rows[1:])
        damaged = copy.deepcopy(rows)
        damaged[1]["before_score"] = 0.1
        damaged[1]["record_sha256"] = canonical_sha(
            {k: v for k, v in damaged[1].items() if k != "record_sha256"}
        )
        with self.assertRaisesRegex(ValueError, "successor"):
            validate_chains(damaged)
        with self.assertRaisesRegex(ValueError, "Persistent"):
            episode_groups(
                [{"schema": "ndu.real.training-transition.v1"}], "persistent"
            )

    def test_legacy_reset_record_remains_admissible(self):
        from .trajectory import V2_FIELDS

        row = {
            k: v
            for k, v in numerical_records(ControlPlan())[0].items()
            if k not in V2_FIELDS
        }
        row["schema"] = "ndu.real.training-transition.v1"
        self.assertEqual(validate_record(row), row)

    def test_reset_collection_is_explicitly_reencoded_for_persistent_training(self):
        rows = numerical_records(ControlPlan(memory_mode="reset"))
        validate_chains(rows)
        self.assertEqual(len(episode_groups(rows, "persistent")), 1)
        metadata = memory_replay_metadata(rows, "persistent")
        self.assertEqual(metadata["replayed_from_memory_modes"], ["reset"])
        self.assertEqual(metadata["collection_memory_mode_rows"], {"reset": 3})
        self.assertFalse(metadata["collection_training_memory_equal"])
        self.assertTrue(metadata["memory_mode_changed_during_replay"])
        self.assertFalse(metadata["on_policy_or_counterfactual_return_claimed"])
        legacy = memory_replay_metadata(
            [{"schema": "ndu.real.training-transition.v1"}], "reset"
        )
        self.assertIsNone(legacy["collection_training_memory_equal"])


if __name__ == "__main__":
    unittest.main()
